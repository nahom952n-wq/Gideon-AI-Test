"""
Notification service — sends scholarship alerts via configured channels.

Phase 1 stub — channel implementations are added in Phase 8.
"""

import logging
from ..models import NotificationLog
from ..extensions import db

log = logging.getLogger("scholarmind.app")


class NotificationService:
    """Sends scholarship notifications via Telegram, email, or desktop."""

    def notify_scholarship(self, scholarship_id: int, channel: str = "telegram") -> bool:
        """
        Send a notification for a scholarship.

        Returns True on success, False on failure.
        Phase 1: logs only — actual sending implemented in Phase 8.
        """
        log.info(
            "Notification queued (scholarship_id=%d, channel=%s) [stub]",
            scholarship_id,
            channel,
        )
        entry = NotificationLog(
            scholarship_id=scholarship_id,
            channel=channel,
            message=f"Scholarship {scholarship_id} notification (stub)",
            status="queued",
        )
        db.session.add(entry)
        db.session.commit()
        return True
