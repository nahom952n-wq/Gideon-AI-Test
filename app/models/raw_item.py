"""
RawItem model — stores original ingested content before any AI processing.

The raw content is NEVER modified after creation. AI analysis and structured
extraction are stored in separate tables so raw data can be re-processed later.
"""

import json
from datetime import datetime
from ..extensions import db


class ProcessingStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class RawItem(db.Model):
    """An unprocessed item from any source, stored verbatim."""

    __tablename__ = "raw_items"

    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey("sources.id"), nullable=False)
    external_id = db.Column(db.String(255), nullable=True)
    raw_content = db.Column(db.Text, nullable=True)
    raw_metadata_json = db.Column(db.Text, default="{}")
    content_hash = db.Column(db.String(64), nullable=True, index=True)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    processed_at = db.Column(db.DateTime, nullable=True)
    processing_status = db.Column(
        db.String(20), default=ProcessingStatus.PENDING, nullable=False, index=True
    )
    error_message = db.Column(db.Text, nullable=True)
    ocr_text = db.Column(db.Text, nullable=True)
    pdf_text = db.Column(db.Text, nullable=True)

    source = db.relationship("Source", back_populates="raw_items")
    scholarship = db.relationship(
        "Scholarship", back_populates="raw_item", uselist=False
    )
    media_attachments = db.relationship(
        "MediaAttachment", back_populates="raw_item", lazy="dynamic"
    )

    __table_args__ = (
        db.UniqueConstraint("source_id", "external_id", name="uq_source_external"),
    )

    @property
    def extra_metadata(self) -> dict:
        try:
            return json.loads(self.raw_metadata_json or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}

    @extra_metadata.setter
    def extra_metadata(self, value: dict) -> None:
        self.raw_metadata_json = json.dumps(value)

    @property
    def effective_text(self) -> str:
        """Return the best available text for AI analysis."""
        return self.pdf_text or self.ocr_text or self.raw_content or ""

    def __repr__(self) -> str:
        return f"<RawItem id={self.id} source_id={self.source_id} status={self.processing_status}>"
