"""
AI response parsers — extract structured data from raw AI text.

Two parsers:
  parse_extraction_response()       — Phase 1/2 scholarship-specific parser
  parse_opportunity_classification() — Phase 3 type classifier
  parse_opportunity_extraction()     — Phase 3 generic opportunity parser

All parsers are pure functions: never raise, always return a dict or string.
"""

import json
import logging
from datetime import date

log = logging.getLogger("scholarmind.ai")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _strip_markdown_fences(text: str) -> str:
    """Remove ```json … ``` or ``` … ``` wrappers if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop first line (```json or ```) and last ``` if present
        inner = lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner)
    return text.strip()


def _safe_float(value) -> float | None:
    try:
        f = float(value)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _safe_int(value) -> int | None:
    try:
        i = int(value)
        return i if i > 0 else None
    except (TypeError, ValueError):
        return None


def _safe_date(value: str) -> date | None:
    if not value or str(value).strip().lower() in ("unknown", "n/a", "none", ""):
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


def _unknown_to_none(v):
    if isinstance(v, str) and v.strip().lower() in ("unknown", "n/a", "none", ""):
        return None
    return v


# ---------------------------------------------------------------------------
# Phase 1/2 — Scholarship extraction parser (preserved for re-analysis)
# ---------------------------------------------------------------------------

def parse_extraction_response(raw_text: str) -> dict:
    """
    Parse raw AI JSON response into a cleaned scholarship dict.

    Returns a dict ready to be unpacked into a Scholarship model.
    All fields default gracefully — never raises.
    """
    cleaned = _strip_markdown_fences(raw_text)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        log.error("Failed to parse AI extraction JSON: %s | raw=%r", e, raw_text[:200])
        return {"ai_confidence": 0.0, "_parse_error": str(e)}

    return {
        "name":                 _unknown_to_none(data.get("name")),
        "university":           _unknown_to_none(data.get("university")),
        "country":              _unknown_to_none(data.get("country")),
        "degree_level":         _unknown_to_none(data.get("degree_level")),
        "funding_type":         _unknown_to_none(data.get("funding_type")),
        "funding_amount":       _unknown_to_none(data.get("funding_amount")),
        "currency":             _unknown_to_none(data.get("currency")),
        "deadline":             _safe_date(data.get("deadline", "")),
        "deadline_raw":         _unknown_to_none(data.get("deadline_raw")),
        "eligibility_text":     _unknown_to_none(data.get("eligibility_text")),
        "required_docs":        data.get("required_docs") if isinstance(data.get("required_docs"), list) else [],
        "min_gpa":              _safe_float(data.get("min_gpa")),
        "ielts_score":          _safe_float(data.get("ielts_score")),
        "toefl_score":          _safe_int(data.get("toefl_score")),
        "english_requirements": _unknown_to_none(data.get("english_requirements")),
        "application_url":      _unknown_to_none(data.get("application_url")),
        "official_website":     _unknown_to_none(data.get("official_website")),
        "fields_of_study":      data.get("fields_of_study") if isinstance(data.get("fields_of_study"), list) else [],
        "keywords":             data.get("keywords") if isinstance(data.get("keywords"), list) else [],
        "summary":              _unknown_to_none(data.get("summary")),
        "application_steps":    data.get("application_steps") if isinstance(data.get("application_steps"), list) else [],
        "ai_confidence":        min(1.0, max(0.0, _safe_float(data.get("confidence")) or 0.0)),
    }


# ---------------------------------------------------------------------------
# Phase 3 — Opportunity classification parser
# ---------------------------------------------------------------------------

_VALID_TYPES = {
    "scholarship", "internship", "fellowship", "grant", "competition",
    "research", "job", "conference", "announcement", "unknown",
}


def parse_opportunity_classification(raw_text: str) -> str:
    """
    Parse a classification AI response and return the opportunity type string.

    Falls back to keyword matching if JSON parsing fails.
    Always returns one of the OpportunityType.ALL values.
    """
    cleaned = _strip_markdown_fences(raw_text)

    # Try JSON first
    try:
        data = json.loads(cleaned)
        opp_type = str(data.get("opportunity_type", "unknown")).lower().strip()
        if opp_type in _VALID_TYPES:
            return opp_type
    except (json.JSONDecodeError, TypeError):
        pass

    # Fall back to keyword scan in the raw text
    lower = cleaned.lower()
    for t in ["scholarship", "internship", "fellowship", "grant", "competition",
              "research", "job", "conference", "announcement"]:
        if t in lower:
            log.debug("parse_opportunity_classification: keyword fallback → %s", t)
            return t

    return "unknown"


# ---------------------------------------------------------------------------
# Phase 3 — Generic opportunity extraction parser
# ---------------------------------------------------------------------------

def parse_opportunity_extraction(raw_text: str) -> dict:
    """
    Parse a generic opportunity extraction AI response → cleaned dict.

    The dict is ready to be consumed by the pipeline store stage.
    Keys that match Opportunity model fields are set directly.
    All other extracted data lands in "_extra_fields" (a nested dict).
    Never raises.
    """
    cleaned = _strip_markdown_fences(raw_text)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        log.error(
            "Failed to parse opportunity extraction JSON: %s | raw=%r",
            e, raw_text[:200],
        )
        return {"ai_confidence": 0.0, "_parse_error": str(e)}

    # Core fields
    result: dict = {
        "title":            _unknown_to_none(data.get("title")),
        "organization":     _unknown_to_none(data.get("organization")),
        "country":          _unknown_to_none(data.get("country")),
        "location":         _unknown_to_none(data.get("location")),
        # deadline kept as string here; stage_validate converts it
        "deadline":         _unknown_to_none(data.get("deadline", "")),
        "deadline_raw":     _unknown_to_none(data.get("deadline_raw")),
        "start_date":       _safe_date(str(data.get("start_date", ""))),
        "summary":          _unknown_to_none(data.get("summary")),
        "eligibility_text": _unknown_to_none(data.get("eligibility_text")),
        "application_url":  _unknown_to_none(data.get("application_url")),
        "official_website": _unknown_to_none(data.get("official_website")),
        "keywords":         data.get("keywords") if isinstance(data.get("keywords"), list) else [],
        "tags":             data.get("tags") if isinstance(data.get("tags"), list) else [],
        "ai_confidence":    min(1.0, max(0.0, _safe_float(data.get("confidence")) or 0.0)),
    }

    # Extra type-specific fields
    extra = data.get("extra_fields", {})
    if not isinstance(extra, dict):
        extra = {}
    # Strip meta / example keys inserted by the prompt template
    result["_extra_fields"] = {
        k: v for k, v in extra.items()
        if k not in ("comment", "examples for scholarships", "examples for internships",
                     "examples for grants", "examples for competitions",
                     "examples for jobs", "examples for conferences")
        and v not in (None, "", "Unknown", "unknown")
    }

    return result
