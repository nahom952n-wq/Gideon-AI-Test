"""
MediaAttachment model — tracks files downloaded from source messages.

Files are stored in storage/{type}/ and referenced by path so they
can be opened from the dashboard without re-downloading.
"""

from datetime import datetime
from ..extensions import db


class MediaAttachment(db.Model):
    """A downloaded file associated with a raw ingested item."""

    __tablename__ = "media_attachments"

    id = db.Column(db.Integer, primary_key=True)
    raw_item_id = db.Column(db.Integer, db.ForeignKey("raw_items.id"), nullable=False)
    file_type = db.Column(db.String(20), nullable=False)
    original_filename = db.Column(db.String(500), nullable=True)
    stored_path = db.Column(db.String(1000), nullable=False)
    file_size = db.Column(db.Integer, nullable=True)
    mime_type = db.Column(db.String(100), nullable=True)
    downloaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    ocr_extracted = db.Column(db.Boolean, default=False)
    text_extracted = db.Column(db.Boolean, default=False)

    raw_item = db.relationship("RawItem", back_populates="media_attachments")

    def __repr__(self) -> str:
        return f"<MediaAttachment id={self.id} type={self.file_type} file={self.original_filename!r}>"
