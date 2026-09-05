"""
Scholarship model — structured AI-extracted data from a raw item.

Stored separately from RawItem so the raw original is preserved and
can be re-analyzed at any time with improved prompts.
"""

import json
from datetime import datetime
from ..extensions import db


class DegreeLevel:
    BACHELOR = "bachelor"
    MASTER = "master"
    PHD = "phd"
    POSTDOC = "postdoc"
    ANY = "any"


class FundingType:
    FULL = "full"
    PARTIAL = "partial"
    TUITION_ONLY = "tuition_only"
    STIPEND_ONLY = "stipend_only"
    UNKNOWN = "unknown"


class Scholarship(db.Model):
    """AI-extracted, structured scholarship record."""

    __tablename__ = "scholarships"

    id = db.Column(db.Integer, primary_key=True)
    raw_item_id = db.Column(
        db.Integer, db.ForeignKey("raw_items.id"), nullable=True
    )

    name = db.Column(db.String(500), nullable=True)
    university = db.Column(db.String(500), nullable=True)
    country = db.Column(db.String(200), nullable=True)
    degree_level = db.Column(db.String(50), nullable=True)
    funding_type = db.Column(db.String(50), nullable=True)
    funding_amount = db.Column(db.String(200), nullable=True)
    currency = db.Column(db.String(10), nullable=True)
    deadline = db.Column(db.Date, nullable=True)
    deadline_raw = db.Column(db.String(200), nullable=True)
    eligibility_text = db.Column(db.Text, nullable=True)
    required_docs_json = db.Column(db.Text, default="[]")
    min_gpa = db.Column(db.Float, nullable=True)
    ielts_score = db.Column(db.Float, nullable=True)
    toefl_score = db.Column(db.Integer, nullable=True)
    english_requirements = db.Column(db.Text, nullable=True)
    application_url = db.Column(db.String(2000), nullable=True)
    official_website = db.Column(db.String(2000), nullable=True)
    fields_of_study_json = db.Column(db.Text, default="[]")
    keywords_json = db.Column(db.Text, default="[]")
    summary = db.Column(db.Text, nullable=True)
    application_steps_json = db.Column(db.Text, default="[]")

    ai_confidence = db.Column(db.Float, default=0.0)
    ai_provider = db.Column(db.String(50), nullable=True)
    ai_model = db.Column(db.String(100), nullable=True)
    ai_prompt_version = db.Column(db.String(20), nullable=True)
    ai_content_hash = db.Column(db.String(64), nullable=True)
    last_analyzed_at = db.Column(db.DateTime, nullable=True)

    duplicate_of_id = db.Column(
        db.Integer, db.ForeignKey("scholarships.id"), nullable=True
    )
    is_duplicate = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    raw_item = db.relationship("RawItem", back_populates="scholarship")
    match_scores = db.relationship("MatchScore", back_populates="scholarship", lazy="dynamic")
    applications = db.relationship("Application", back_populates="scholarship", lazy="dynamic")
    notification_logs = db.relationship("NotificationLog", back_populates="scholarship", lazy="dynamic")

    @property
    def required_docs(self) -> list:
        try:
            return json.loads(self.required_docs_json or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    @required_docs.setter
    def required_docs(self, value: list) -> None:
        self.required_docs_json = json.dumps(value)

    @property
    def fields_of_study(self) -> list:
        try:
            return json.loads(self.fields_of_study_json or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    @fields_of_study.setter
    def fields_of_study(self, value: list) -> None:
        self.fields_of_study_json = json.dumps(value)

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
    def application_steps(self) -> list:
        try:
            return json.loads(self.application_steps_json or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    @application_steps.setter
    def application_steps(self, value: list) -> None:
        self.application_steps_json = json.dumps(value)

    @property
    def days_until_deadline(self) -> int | None:
        if not self.deadline:
            return None
        return (self.deadline - datetime.utcnow().date()).days

    @property
    def is_deadline_soon(self) -> bool:
        days = self.days_until_deadline
        return days is not None and 0 <= days <= 30

    @property
    def is_expired(self) -> bool:
        days = self.days_until_deadline
        return days is not None and days < 0

    def __repr__(self) -> str:
        return f"<Scholarship id={self.id} name={self.name!r} country={self.country!r}>"
