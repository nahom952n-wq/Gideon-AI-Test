"""
Enrichment service — RawItem → Opportunity pipeline orchestrator.

Phase 3 change: delegates all AI processing to ProcessingPipeline.
The pipeline writes to the Opportunity table (generic, multi-type).
The old Scholarship path is preserved via enrich_one_legacy() for
any re-analysis of records that pre-date Phase 3.

Designed to be called from:
  - The APScheduler background job (batch, rate-limited)
  - The "Re-analyze" button on an opportunity detail page
"""

import logging
from datetime import datetime
from flask import current_app
from ..extensions import db
from ..models import RawItem
from ..models.opportunity import Opportunity
from ..services.pipeline import ProcessingPipeline
from ..ai.router import AIRouter
from ..ai.prompts import EXTRACTION_SYSTEM, EXTRACTION_PROMPT_TEMPLATE, EXTRACTION_PROMPT_VERSION
from ..ai.extractor import parse_extraction_response

log = logging.getLogger("scholarmind.ai")


class EnrichmentService:
    """
    Batch-processes pending RawItems through the AI pipeline.

    Phase 3: process_pending() uses ProcessingPipeline → Opportunity table.
    Legacy: enrich_one_legacy() writes to the old Scholarship table (backward compat).
    """

    def __init__(self) -> None:
        self._pipeline = ProcessingPipeline()
        self._router   = AIRouter()

    # ------------------------------------------------------------------
    # Primary path — Phase 3 pipeline
    # ------------------------------------------------------------------

    def process_pending(self, batch_size: int | None = None) -> int:
        """
        Process a batch of pending raw items through the Phase 3 pipeline.

        Args:
            batch_size: Max items to process. Defaults to app config value.

        Returns:
            Number of items successfully enriched (Opportunity created/updated).
        """
        if batch_size is None:
            batch_size = current_app.config.get("AI_ENRICHMENT_RATE", 5)

        pending = (
            RawItem.query
            .filter_by(processing_status="pending")
            .order_by(RawItem.fetched_at.asc())
            .limit(batch_size)
            .all()
        )

        if not pending:
            return 0

        log.info("EnrichmentService: processing %d pending raw items", len(pending))
        count = 0
        for raw in pending:
            if self._run_pipeline(raw):
                count += 1

        return count

    def enrich_one(self, raw_item: RawItem) -> bool:
        """
        Force-process a single raw item through the Phase 3 pipeline.

        Called by the "Re-analyze" button on the opportunity detail page.
        """
        return self._run_pipeline(raw_item)

    def _run_pipeline(self, raw: RawItem) -> bool:
        """
        Execute the full pipeline on one RawItem and update its status.

        Returns True on success, False on failure.
        """
        raw.processing_status = "processing"
        db.session.commit()

        opportunity = self._pipeline.run(raw)

        if opportunity is None:
            raw.processing_status = "failed"
            raw.error_message = "Pipeline returned no result"
            db.session.commit()
            log.error(
                "EnrichmentService: pipeline failed for raw_item id=%d", raw.id
            )
            return False

        raw.processing_status = "done"
        raw.processed_at = datetime.utcnow()
        raw.error_message = None
        db.session.commit()

        log.info(
            "EnrichmentService: raw_item id=%d → Opportunity id=%d (type=%s score=%d)",
            raw.id, opportunity.id, opportunity.opportunity_type, opportunity.opportunity_score,
        )
        return True

    # ------------------------------------------------------------------
    # Legacy path — Phase 1/2 Scholarship extraction (backward compat)
    # ------------------------------------------------------------------

    def enrich_one_legacy(self, raw_item: RawItem) -> bool:
        """
        Re-analyze a raw item using the Phase 1/2 scholarship-specific prompt.

        Writes to the Scholarship table. Use this only for records that were
        originally processed before Phase 3.
        """
        import hashlib
        from ..models import Scholarship

        raw = raw_item
        raw.processing_status = "processing"
        db.session.commit()

        text = raw.effective_text
        if not text.strip():
            raw.processing_status = "skipped"
            db.session.commit()
            return False

        content_hash = hashlib.sha256(text.encode()).hexdigest()
        existing = Scholarship.query.filter_by(
            ai_content_hash=content_hash,
            ai_prompt_version=EXTRACTION_PROMPT_VERSION,
        ).first()
        if existing and existing.raw_item_id != raw.id:
            raw.processing_status = "done"
            raw.processed_at = datetime.utcnow()
            db.session.commit()
            return True

        prompt = EXTRACTION_PROMPT_TEMPLATE.format(text=text[:8000])
        response = self._router.route("extraction", prompt, system=EXTRACTION_SYSTEM)

        if not response.success:
            raw.processing_status = "failed"
            raw.error_message = response.error
            db.session.commit()
            return False

        extracted = parse_extraction_response(response.text)
        scholarship = Scholarship.query.filter_by(raw_item_id=raw.id).first()
        if not scholarship:
            from ..models import Scholarship as S
            scholarship = S(raw_item_id=raw.id)
            db.session.add(scholarship)

        for key, value in extracted.items():
            if key.startswith("_"):
                continue
            if hasattr(scholarship, key):
                setattr(scholarship, key, value)
            elif key in ("required_docs", "fields_of_study", "keywords", "application_steps"):
                setattr(scholarship, key, value)

        scholarship.ai_provider        = response.provider
        scholarship.ai_model           = response.model
        scholarship.ai_prompt_version  = EXTRACTION_PROMPT_VERSION
        scholarship.ai_content_hash    = content_hash
        scholarship.last_analyzed_at   = datetime.utcnow()

        raw.processing_status = "done"
        raw.processed_at = datetime.utcnow()
        db.session.commit()

        log.info(
            "Legacy enrichment: Scholarship id=%d from raw_item id=%d",
            scholarship.id, raw.id,
        )
        return True
