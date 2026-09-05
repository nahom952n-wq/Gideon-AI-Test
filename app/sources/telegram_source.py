"""
Telegram source adapter — wraps TelegramService into the BaseSource interface.

Config keys (stored in Source.config_json):
    channel     : str   — channel username (e.g. "@scholarships") or numeric ID
    limit       : int   — max messages per fetch (default 100)
    since_hours : int   — look back window in hours (default 24)
    min_length  : int   — minimum text length to keep a message (default 30)
"""

import logging
from datetime import datetime
from .base import BaseSource, RawItemData

log = logging.getLogger("scholarmind.telegram")


class TelegramSource(BaseSource):
    """Fetches messages from a Telegram channel using the Telethon userbot."""

    source_type = "telegram"

    def fetch(self) -> list[RawItemData]:
        channel = self.config.get("channel", "")
        if not channel:
            log.warning("TelegramSource id=%d: no channel configured", self.source_id)
            return []

        limit = int(self.config.get("limit", 100))
        since_hours = int(self.config.get("since_hours", 24))
        min_length = int(self.config.get("min_length", 30))

        from ..services.telegram_service import get_service
        service = get_service()
        if not service or not service.is_connected():
            log.warning(
                "TelegramSource id=%d: client not connected, skipping fetch", self.source_id
            )
            return []

        from flask import current_app
        storage_dir = current_app.config.get("STORAGE_DIR")
        media_dir = (storage_dir / "telegram") if storage_dir else None
        if media_dir:
            media_dir.mkdir(parents=True, exist_ok=True)

        try:
            raw_msgs = service.fetch_channel(
                channel=channel,
                source_id=self.source_id,
                limit=limit,
                since_hours=since_hours,
                min_text_length=min_length,
                storage_dir=media_dir,
            )
        except Exception as exc:
            log.exception("TelegramSource id=%d: fetch failed for %r", self.source_id, channel)
            raise RuntimeError(
                f"Could not fetch Telegram channel {channel!r}: {exc}"
            ) from exc

        items = []
        for msg in raw_msgs:
            items.append(
                RawItemData(
                    source_id=self.source_id,
                    external_id=msg["external_id"],
                    raw_content=msg["raw_content"],
                    raw_metadata=msg["raw_metadata"],
                    fetched_at=msg["fetched_at"],
                    media_urls=[],
                )
            )
        log.info(
            "TelegramSource id=%d channel=%s: fetched %d items",
            self.source_id,
            channel,
            len(items),
        )
        return items

    def health_check(self) -> tuple[str, str]:
        channel = self.config.get("channel", "")
        if not channel:
            return "error", "No channel configured"

        from ..services.telegram_service import get_service
        service = get_service()
        if not service:
            return "error", "Telegram credentials not set in .env"
        if not service.is_connected():
            return "error", "Not connected — complete Telegram setup"

        return service.health_check_channel(channel)
