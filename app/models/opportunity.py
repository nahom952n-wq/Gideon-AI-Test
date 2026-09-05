"""
Opportunity model — generic AI-extracted record for any opportunity type.

Introduced in Phase 3. Replaces the scholarship-specific model as the
primary output target of the processing pipeline.

The Scholarship model is preserved unchanged for backward compatibility
with any existing records.

Design notes:
- Core fields cover identity, timeline, and content (all types).
- Type-specific payload (funding_amount, prize, salary, etc.) is stored
  in extra_fields_json so the schema never needs altering for new types.
- raw_ai_output stores the full AI response JSON for debugging and
  selective reprocessing.
- processing_version lets future prompt upgrades reprocess only the
  records extracted with older versions.
"""

import json
from datetime import datetime
from ..extensions import db


class OpportunityType:
    """Enumeration of supported opportunity types."""

    SCHOLARSHIP  = "scholarship"
    INTERNSHIP   = "internship"
    FELLOWSHIP   = "fellowship"
    GRANT        = "grant"
    COMPETITION  = "competition"
    RESEARCH     = "research"
    JOB          = "job"
    CONFERENCE   = "conference"
    ANNOUNCEMENT = "announcement"
    UNKNOWN      = "unknown"

    ALL = [
        SCHOLARSHIP, INTERNSHIP, FELLOWSHIP, GRANT, COMPETITION,
        RESEARCH, JOB, CONFERENCE, ANNOUNCEMENT, UNKNOWN,
    ]

    ICONS = {
        SCHOLARSHIP:  "bi-mortarboard-fill",
        INTERNSHIP:   "bi-briefcase-fill",
        FELLOWSHIP:   "bi-award-fill",
        GRANT:        "bi-cash-stack",
        COMPETITION:  "bi-trophy-fill",
        RESEARCH:     "bi-microscope",
        JOB:          "bi-building-fill",
        CONFERENCE:   "bi-people-fill",
        ANNOUNCEMENT: "bi-megaphone-fill",
        UNKNOWN:      "bi-question-circle-fill",
    }

    COLORS = {
        SCHOLARSHIP:  "primary",
        INTERNSHIP:   "success",
        FELLOWSHIP:   "info",
        GRANT:        "warning",
        COMPETITION:  "danger",
        RESEARCH:     "secondary",
        JOB:          "dark",
        CONFERENCE:   "info",
        ANNOUNCEMENT: "warning",
        UNKNOWN:      "secondary",
    }

    LABELS = {
        SCHOLARSHIP:  "Scholarship",
        INTERNSHIP:   "Internship",
        FELLOWSHIP:   "Fellowship",
        GRANT:        "Grant",
        COMPETITION:  "Competition",
        RESEARCH:     "Research",
        JOB:          "Job",
        CONFERENCE:   "Conference",
        ANNOUNCEMENT: "Announcement",
        UNKNOWN:      "Unknown",
    }


class Opportunity(db.Model):
    """
    Generic AI-extracted opportunity — works for any opportunity type.

    The pipeline writes one Opportunity per RawItem. All types share this
    table; type-specific extra data is stored in extra_fields_json.
    """

    __tablename__ = "opportunities"

    id = db.Column(db.Integer, primary_key=True)
    raw_item_id = db.Column(
        db.Integer, db.ForeignKey("raw_items.id"), nullable=True, index=True
    )

    # --- Core identity ---
    opportunity_type = db.Column(
        db.String(50),
        default=OpportunityType.UNKNOWN,
        nullable=False,
        index=True,
    )
    title = db.Column(db.String(500), nullable=True)
    organization = db.Column(db.String(500), nullable=True)
    country = db.Column(db.String(200), nullable=True, index=True)
    location = db.Column(db.String(500), nullable=True)

    # --- Timeline ---
    deadline = db.Column(db.Date, nullable=True, index=True)
    deadline_raw = db.Column(db.String(200), nullable=True)
    start_date = db.Column(db.Date, nullable=True)

    # --- Content ---
    summary = db.Column(db.Text, nullable=True)
    eligibility_text = db.Column(db.Text, nullable=True)
    application_url = db.Column(db.String(2000), nullable=True)
    official_website = db.Column(db.String(2000), nullable=True)

    # --- Flexible type-specific payload ---
    # Stores type-specific fields not in the core schema:
    #   scholarships → funding_amount, currency, degree_level, min_gpa
    #   internships  → duration, compensation, remote
    #   competitions → prize, submission_format
    #   jobs         → salary, contract_type, remote
    #   conferences  → venue, registration_fee, paper_deadline
    extra_fields_json = db.Column(db.Text, default="{}")

    # --- Taxonomy ---
    keywords_json = db.Column(db.Text, default="[]")
    tags_json = db.Column(db.Text, default="[]")

    # --- AI pipeline metadata ---
    raw_ai_output = db.Column(db.Text, nullable=True)     # Full raw JSON from AI
    processing_version = db.Column(db.String(20), default="3.0", index=True)
    ai_confidence = db.Column(db.Float, default=0.0)
    ai_provider = db.Column(db.String(50), nullable=True)
    ai_model = db.Column(db.String(100), nullable=True)
    ai_content_hash = db.Column(db.String(64), nullable=True, index=True)
    last_analyzed_at = db.Column(db.DateTime, nullable=True)

    # --- Scoring ---
    opportunity_score = db.Column(db.Integer, default=0)  # 0-100

    # --- Status ---
    is_duplicate = db.Column(db.Boolean, default=False)
    duplicate_of_id = db.Column(
        db.Integer, db.ForeignKey("opportunities.id"), nullable=True
    )
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # --- Relationships ---
    raw_item = db.relationship("RawItem", foreign_keys=[raw_item_id])
    applications = db.relationship("Application", back_populates="opportunity", lazy="dynamic")

    # --- JSON helpers ---

    @property
    def extra_fields(self) -> dict:
        try:
            return json.loads(self.extra_fields_json or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}

    @extra_fields.setter
    def extra_fields(self, value: dict) -> None:
        self.extra_fields_json = json.dumps(value)

    @property
    def keywords(self) -> list:
        try:
            return json.loads(self.keywords_json or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    @keywords.setter
    def keywords(self, value: list) -> None:
        self.keywords_json = json.dumps(value)

    @property
    def tags(self) -> list:
        try:
            return json.loads(self.tags_json or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    @tags.setter
    def tags(self, value: list) -> None:
        self.tags_json = json.dumps(value)

    # --- Computed properties ---

    @property
    def days_until_deadline(self) -> int | None:
        if not self.deadline:
            return None
        return (self.deadline - datetime.utcnow().date()).days

    @property
    def is_deadline_soon(self) -> bool:
        d = self.days_until_deadline
        return d is not None and 0 <= d <= 30

    @property
    def is_expired(self) -> bool:
        d = self.days_until_deadline
        return d is not None and d < 0

    @property
    def type_icon(self) -> str:
        return OpportunityType.ICONS.get(
            self.opportunity_type, "bi-question-circle-fill"
        )

    @property
    def type_color(self) -> str:
        return OpportunityType.COLORS.get(self.opportunity_type, "secondary")

    @property
    def type_label(self) -> str:
        return OpportunityType.LABELS.get(
            self.opportunity_type, self.opportunity_type.title()
        )

    def __repr__(self) -> str:
        return (
            f"<Opportunity id={self.id} type={self.opportunity_type!r} "
            f"title={self.title!r}>"
        )
