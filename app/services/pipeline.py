"""
ProcessingPipeline — modular 8-stage opportunity extraction pipeline.

Stage contract
--------------
Each stage is a method stage_<name>(ctx: dict) → StageResult.
ctx is a mutable dict passed through all stages; stages read and write it freely.
Returning StageResult(success=False) halts the pipeline (returns None to caller).
Returning StageResult(skipped=True) logs and continues without halting.

Stages (executed in order)
---------------------------
  1. preprocess  — normalize and clean raw text
  2. media       — combine media attachment text with message text
  3. classify    — AI: determine opportunity type
  4. extract     — AI: structured field extraction
  5. validate    — normalize dates, apply sensible defaults
  6. confidence  — evaluate AI confidence score
  7. score       — compute opportunity_score 0–100
  8. store       — write or update the Opportunity record

Usage
-----
  pipeline = ProcessingPipeline()
  opportunity = pipeline.run(raw_item)
  # Returns the Opportunity on success, None on failure.
"""

import hashlib
import json
import logging
from datetime import datetime
from typing import Optional

from flask import current_app

from ..extensions import db
from ..models import RawItem
from ..models.opportunity import Opportunity, OpportunityType
from ..ai.router import AIRouter
from ..ai.prompts import (
    CLASSIFICATION_PROMPT_TEMPLATE,
    OPPORTUNITY_EXTRACTION_SYSTEM,
    OPPORTUNITY_EXTRACTION_PROMPT_TEMPLATE,
    PROCESSING_VERSION,
)
from ..ai.extractor import (
    parse_opportunity_classification,
    parse_opportunity_extraction,
    _safe_date,
)

log = logging.getLogger("scholarmind.ai")


# ---------------------------------------------------------------------------
# Stage result
# ---------------------------------------------------------------------------

class StageResult:
    """Lightweight result container for a single pipeline stage."""

    __slots__ = ("success", "data", "error", "skipped")

    def __init__(
        self,
        success: bool = True,
        data: dict | None = None,
        error: str | None = None,
        skipped: bool = False,
    ) -> None:
        self.success = success
        self.data = data or {}
        self.error = error
        self.skipped = skipped

    def __repr__(self) -> str:
        return (
            f"StageResult(success={self.success}, skipped={self.skipped}, "
            f"error={self.error!r})"
        )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class ProcessingPipeline:
    """
    Processes a RawItem through 8 independent stages and produces an Opportunity.

    Each stage is independently replaceable — swap out stage_classify() for a
    rule-based classifier, or stage_extract() for a different prompt, without
    touching anything else.
    """

    def __init__(self) -> None:
        self._router = AIRouter()

    def run(self, raw: RawItem) -> Optional[Opportunity]:
        """
        Execute the full pipeline on one RawItem.

        Returns the Opportunity on success, None on any unrecoverable failure.
        """
        ctx: dict = {
            "raw":             raw,
            "text":            "",
            "text_for_ai":     "",
            "opportunity_type": OpportunityType.UNKNOWN,
            "extracted":       {},
            "raw_ai_output":   {},
            "confidence":      0.0,
            "ai_provider":     None,
            "ai_model":        None,
            "opportunity_score": 0,
            "opportunity":     None,
        }

        stages = [
            ("preprocess", self.stage_preprocess),
            ("media",      self.stage_media),
            ("classify",   self.stage_classify),
            ("extract",    self.stage_extract),
            ("validate",   self.stage_validate),
            ("confidence", self.stage_confidence),
            ("score",      self.stage_score),
            ("store",      self.stage_store),
        ]

        for stage_name, stage_fn in stages:
            try:
                result: StageResult = stage_fn(ctx)
            except Exception as exc:
                log.exception(
                    "Pipeline stage '%s' raised for raw_item id=%d: %s",
                    stage_name, raw.id, exc,
                )
                return None

            if result.skipped:
                log.debug(
                    "Pipeline: stage '%s' skipped for raw_item id=%d",
                    stage_name, raw.id,
                )
                continue

            if not result.success:
                log.error(
                    "Pipeline: stage '%s' FAILED for raw_item id=%d: %s",
                    stage_name, raw.id, result.error,
                )
                return None

            # Merge stage data into shared context
            ctx.update(result.data)

        return ctx.get("opportunity")

    # ------------------------------------------------------------------
    # Stage 1: Pre-processing
    # ------------------------------------------------------------------

    def stage_preprocess(self, ctx: dict) -> StageResult:
        """Normalize and clean the raw item text; reject empty items early."""
        raw: RawItem = ctx["raw"]
        text = (raw.effective_text or "").strip()

        if not text:
            return StageResult(
                success=False,
                error="No extractable text in raw item",
            )

        # Normalize line endings and remove blank lines
        lines = [ln.strip() for ln in text.splitlines()]
        text = "\n".join(ln for ln in lines if ln)

        return StageResult(data={
            "text": text,
            "text_for_ai": text[:8000],
        })

    # ------------------------------------------------------------------
    # Stage 2: Media processing
    # ------------------------------------------------------------------

    def stage_media(self, ctx: dict) -> StageResult:
        """
        Combine extracted media text (PDF, OCR, attachments) with the
        message body, then re-slice for the AI budget.
        """
        raw: RawItem = ctx["raw"]
        text: str = ctx["text"]

        parts: list[str] = []

        if raw.pdf_text:
            parts.append(f"[PDF Content]\n{raw.pdf_text[:3000]}")
        if raw.ocr_text:
            parts.append(f"[Image/OCR Content]\n{raw.ocr_text[:3000]}")

        # Pull text from media_attachments table
        try:
            for ma in raw.media_attachments:
                if getattr(ma, "extracted_text", None):
                    parts.append(
                        f"[Attachment: {ma.filename}]\n{ma.extracted_text[:2000]}"
                    )
        except Exception:
            pass

        if not parts:
            return StageResult(skipped=True)

        combined = text + "\n\n" + "\n\n".join(parts)
        log.debug(
            "Pipeline media: combined text with %d attachment(s) for raw_item id=%d",
            len(parts), raw.id,
        )
        return StageResult(data={
            "text": combined,
            "text_for_ai": combined[:8000],
        })

    # ------------------------------------------------------------------
    # Stage 3: Opportunity Classification
    # ------------------------------------------------------------------

    def stage_classify(self, ctx: dict) -> StageResult:
        """
        Ask the AI to classify the opportunity type.

        Non-fatal: if classification fails, we default to 'unknown' and
        continue so the extraction stage still runs.
        """
        text_snippet = ctx["text_for_ai"][:4000]
        prompt = CLASSIFICATION_PROMPT_TEMPLATE.format(text=text_snippet)

        response = self._router.route_capability("classification", prompt)

        if not response.success:
            log.warning(
                "Classification AI failed for raw_item id=%d: %s — defaulting to 'unknown'",
                ctx["raw"].id, response.error,
            )
            return StageResult(data={"opportunity_type": OpportunityType.UNKNOWN})

        opp_type = parse_opportunity_classification(response.text)
        log.info(
            "Pipeline classify: raw_item id=%d → type='%s'",
            ctx["raw"].id, opp_type,
        )
        return StageResult(data={"opportunity_type": opp_type})

    # ------------------------------------------------------------------
    # Stage 4: Field Extraction
    # ------------------------------------------------------------------

    def stage_extract(self, ctx: dict) -> StageResult:
        """
        Run structured field extraction for the detected opportunity type.

        Uses route_capability("structured_extraction") which applies
        local-first / cloud-fallback logic from the AIRouter.
        """
        opp_type: str = ctx["opportunity_type"]
        text_for_ai: str = ctx["text_for_ai"]

        prompt = OPPORTUNITY_EXTRACTION_PROMPT_TEMPLATE.format(
            opportunity_type=opp_type,
            text=text_for_ai,
        )
        response = self._router.route_capability(
            "structured_extraction",
            prompt,
            system=OPPORTUNITY_EXTRACTION_SYSTEM,
        )

        if not response.success:
            return StageResult(success=False, error=response.error)

        extracted = parse_opportunity_extraction(response.text)

        # Log parse errors but don't halt — partial extraction is better than none
        if "_parse_error" in extracted:
            log.warning(
                "Pipeline extract: JSON parse error for raw_item id=%d: %s",
                ctx["raw"].id, extracted["_parse_error"],
            )

        return StageResult(data={
            "extracted":   extracted,
            "raw_ai_output": {
                "classification": opp_type,
                "extraction_raw": response.text,
                "provider": response.provider,
                "model":    response.model,
            },
            "ai_provider": response.provider,
            "ai_model":    response.model,
        })

    # ------------------------------------------------------------------
    # Stage 5: Validation
    # ------------------------------------------------------------------

    def stage_validate(self, ctx: dict) -> StageResult:
        """
        Normalize dates, enforce valid opportunity_type, strip parse artifacts.
        """
        extracted: dict = dict(ctx["extracted"])

        # Normalize deadline string → date object
        deadline_str = extracted.get("deadline")
        if isinstance(deadline_str, str):
            extracted["deadline"] = _safe_date(deadline_str)

        # Validate opportunity_type
        opp_type: str = ctx.get("opportunity_type", OpportunityType.UNKNOWN)
        if opp_type not in OpportunityType.ALL:
            opp_type = OpportunityType.UNKNOWN
        extracted["opportunity_type"] = opp_type

        return StageResult(data={
            "extracted":        extracted,
            "opportunity_type": opp_type,
        })

    # ------------------------------------------------------------------
    # Stage 6: Confidence Evaluation
    # ------------------------------------------------------------------

    def stage_confidence(self, ctx: dict) -> StageResult:
        """
        Read the AI-declared confidence from the extracted payload.

        The router already handles local→cloud escalation before we get here,
        so this stage is primarily for logging and scoring purposes.
        """
        extracted: dict = ctx["extracted"]
        confidence = float(extracted.pop("ai_confidence", 0.0))

        threshold = current_app.config.get("LOCAL_AI_CONFIDENCE_THRESHOLD", 0.60)
        log.debug(
            "Pipeline confidence: raw_item id=%d confidence=%.2f threshold=%.2f",
            ctx["raw"].id, confidence, threshold,
        )
        return StageResult(data={"confidence": confidence})

    # ------------------------------------------------------------------
    # Stage 7: Scoring
    # ------------------------------------------------------------------

    def stage_score(self, ctx: dict) -> StageResult:
        """
        Compute opportunity_score 0–100 based on AI confidence + field completeness.

        Score breakdown (max 100):
          60 pts — AI confidence (scaled)
          10 pts — has title
          10 pts — has deadline
          10 pts — has application_url
           5 pts — has organization
           5 pts — has summary
        """
        extracted: dict = ctx["extracted"]
        confidence: float = ctx.get("confidence", 0.0)

        score = int(confidence * 60)
        if extracted.get("title"):
            score += 10
        if extracted.get("deadline"):
            score += 10
        if extracted.get("application_url"):
            score += 10
        if extracted.get("organization"):
            score += 5
        if extracted.get("summary"):
            score += 5

        score = min(100, max(0, score))
        return StageResult(data={"opportunity_score": score})

    # ------------------------------------------------------------------
    # Stage 8: Storage
    # ------------------------------------------------------------------

    def stage_store(self, ctx: dict) -> StageResult:
        """
        Write or update the Opportunity record.

        Deduplication is based on (content_hash, processing_version).
        If the same content has already been processed at the same version,
        the existing record is reused without re-writing.
        """
        raw: RawItem = ctx["raw"]
        extracted: dict = ctx["extracted"]
        text: str = ctx["text"]

        content_hash = hashlib.sha256(
            text.encode("utf-8", errors="replace")
        ).hexdigest()

        # Deduplicate by content hash + processing version
        existing = Opportunity.query.filter_by(
            ai_content_hash=content_hash,
            processing_version=PROCESSING_VERSION,
        ).first()
        if existing and existing.raw_item_id != raw.id:
            log.info(
                "Pipeline store: reusing Opportunity id=%d (hash=%s) for raw_item id=%d",
                existing.id, content_hash[:12], raw.id,
            )
            return StageResult(data={"opportunity": existing})

        # Upsert: find existing record for this raw_item or create new
        opp = Opportunity.query.filter_by(raw_item_id=raw.id).first()
        if not opp:
            opp = Opportunity(raw_item_id=raw.id)
            db.session.add(opp)

        # Core model fields
        _CORE = {
            "opportunity_type", "title", "organization", "country", "location",
            "deadline", "deadline_raw", "start_date", "summary",
            "eligibility_text", "application_url", "official_website",
        }
        for key, value in extracted.items():
            if key.startswith("_"):
                continue
            if key in _CORE and hasattr(opp, key):
                setattr(opp, key, value)

        # Taxonomy
        opp.keywords = extracted.get("keywords") or []
        opp.tags     = extracted.get("tags") or []

        # Type-specific extra fields
        opp.extra_fields = extracted.get("_extra_fields") or {}

        # AI metadata
        opp.ai_confidence      = ctx.get("confidence", 0.0)
        opp.ai_provider        = ctx.get("ai_provider")
        opp.ai_model           = ctx.get("ai_model")
        opp.ai_content_hash    = content_hash
        opp.processing_version = PROCESSING_VERSION
        opp.last_analyzed_at   = datetime.utcnow()
        opp.opportunity_score  = ctx.get("opportunity_score", 0)
        opp.raw_ai_output      = json.dumps(ctx.get("raw_ai_output", {}))

        db.session.commit()

        log.info(
            "Pipeline store: Opportunity id=%d (type=%s score=%d confidence=%.2f) "
            "← raw_item id=%d",
            opp.id,
            opp.opportunity_type,
            opp.opportunity_score,
            opp.ai_confidence,
            raw.id,
        )
        return StageResult(data={"opportunity": opp})
