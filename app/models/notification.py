"""
NotificationLog model — records every notification sent to the user.

Prevents duplicate notifications and gives a full history.
"""

from datetime import datetime
from ..extensions import db


class NotificationChannel:
    TELEGRAM = "telegram"
    EMAIL = "email"
    DESKTOP = "desktop"


class NotificationLog(db.Model):
    """A record of a notification that was sent (or attempted)."""

    __tablename__ = "notification_log"

    id = db.Column(db.Integer, primary_key=True)
    scholarship_id = db.Column(
        db.Integer, db.ForeignKey("scholarships.id"), nullable=True
    )
    channel = db.Column(db.String(30), nullable=False)
    message = db.Column(db.Text, nullable=True)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    status = db.Column(db.String(20), default="sent", nullable=False)
    error_message = db.Column(db.Text, nullable=True)

    scholarship = db.relationship("Scholarship", back_populates="notification_logs")

    def __repr__(self) -> str:
        return f"<NotificationLog id={self.id} channel={self.channel} status={self.status}>"
