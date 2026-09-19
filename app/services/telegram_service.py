"""
Telegram service — manages a Telethon userbot client for ScholarMind AI.

Architecture:
  - A single asyncio event loop runs in a daemon background thread so
    synchronous Flask routes can submit coroutines via
    asyncio.run_coroutine_threadsafe().
  - The client connects once and is kept alive; reconnect is automatic.
  - Session file is written to SESSIONS_DIR/scholarmind.session (gitignored).

OTP auth flow:
  1. Call send_code(phone)  →  stores phone_code_hash in caller's session dict
  2. Call sign_in(phone, code, phone_code_hash)  →  logs in and saves session
  3. Subsequent startups: client.start() restores the saved session silently.
"""

import asyncio
import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("scholarmind.telegram")


class TelegramTwoFactorRequired(RuntimeError):
    """Raised when Telegram requires the account's 2FA password."""

    def __init__(self, hint: str = "") -> None:
        self.hint = hint
        super().__init__("Telegram two-step verification is required")


# ---------------------------------------------------------------------------
# Background event loop — one loop per process, lives in a daemon thread
# ---------------------------------------------------------------------------
_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
_loop_thread = threading.Thread(
    target=_loop.run_forever, daemon=True, name="telethon-loop"
)
_loop_thread.start()


def _run(coro, timeout: int = 60):
    """Submit a coroutine to the background loop and block until done."""
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=timeout)


def _extract_text_from_file(path: str) -> str:
    """
    Best-effort text extraction from a downloaded media file.

    Currently handles plain text files and basic PDF reading.
    Images are noted for later OCR in the AI enrichment pipeline.
    Returns empty string on failure — never raises.
    """
    try:
        p = Path(path)
        suffix = p.suffix.lower()

        if suffix in (".txt", ".md", ".html", ".htm"):
            return p.read_text(encoding="utf-8", errors="replace")[:8000]

        if suffix == ".pdf":
            try:
                import pdfminer.high_level as pdfminer
                text = pdfminer.extract_text(str(p))
                return (text or "")[:8000]
            except ImportError:
                # pdfminer not installed — note for enrichment pipeline
                return f"[PDF attached: {p.name} — text extraction pending]"
            except Exception:
                return f"[PDF attached: {p.name}]"

        if suffix in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
            # Image: flag for vision/OCR in enrichment phase
            return f"[Image attached: {p.name} — OCR pending]"

        # Unknown type — note it exists
        return f"[Attachment: {p.name}]"

    except Exception as exc:
        log.debug("_extract_text_from_file failed for %s: %s", path, exc)
        return ""


# ---------------------------------------------------------------------------
# TelegramService
# ---------------------------------------------------------------------------
class TelegramService:
    """
    Wraps a Telethon TelegramClient with a synchronous interface.

    Intended as a singleton — call get_service() instead of constructing directly.
    """

    def __init__(self, api_id: int, api_hash: str, session_path: Path) -> None:
        from telethon import TelegramClient

        self._api_id = api_id
        self._api_hash = api_hash
        self._session_path = session_path
        self._client: Optional[TelegramClient] = None
        self._connected = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _get_client(self):
        """Lazily create the TelegramClient (not connected yet)."""
        from telethon import TelegramClient

        if self._client is not None:
            return self._client

        # Telethon inspects the currently running loop while constructing the
        # client. Flask invokes this method from request threads, which do not
        # have an asyncio loop on Python 3.14, so construct it on the
        # dedicated Telethon loop instead.
        with self._lock:
            if self._client is None:
                async def _create_client():
                    return TelegramClient(
                        str(self._session_path),
                        self._api_id,
                        self._api_hash,
                        loop=_loop,
                    )

                self._client = _run(_create_client())
        return self._client

    def connect_saved_session(self) -> bool:
        """
        Try to connect using a saved session file.

        Returns True if already authorised, False if OTP is required.
        """
        client = self._get_client()
        try:
            _run(client.connect())
            authorised = _run(client.is_user_authorized())
            self._connected = authorised
            if authorised:
                log.info("Telegram: restored saved session — authorised")
            else:
                log.info("Telegram: connected but not authorised (OTP required)")
            return authorised
        except Exception as exc:
            log.error("Telegram: connect_saved_session failed: %s", exc)
            self._connected = False
            return False

    def send_code(self, phone: str) -> str:
        """
        Send the Telegram sign-in OTP to *phone*.

        Returns:
            phone_code_hash — must be passed back to sign_in().
        Raises:
            RuntimeError on Telegram API errors.
        """
        client = self._get_client()
        try:
            _run(client.connect())
            sent = _run(client.send_code_request(phone))
            log.info("Telegram: OTP sent to %s", phone)
            return sent.phone_code_hash
        except Exception as exc:
            log.error("Telegram: send_code failed: %s", exc)
            raise RuntimeError(f"Could not send OTP: {exc}") from exc

    def sign_in(self, phone: str, code: str, phone_code_hash: str) -> bool:
        """
        Complete sign-in with the OTP code.

        Returns True on success.
        Raises RuntimeError on failure.
        """
        client = self._get_client()
        try:
            _run(client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash))
            self._connected = True
            log.info("Telegram: signed in successfully")
            return True
        except Exception as exc:
            from telethon.errors import SessionPasswordNeededError

            if isinstance(exc, SessionPasswordNeededError):
                hint = self.get_password_hint()
                log.info("Telegram: OTP accepted; two-step verification required")
                raise TelegramTwoFactorRequired(hint) from exc
            log.error("Telegram: sign_in failed: %s", exc)
            raise RuntimeError(f"Sign-in failed: {exc}") from exc

    def get_password_hint(self) -> str:
        """Return the account's Telegram 2FA password hint."""
        from telethon.tl import functions

        client = self._get_client()
        password = _run(client(functions.account.GetPasswordRequest()))
        return password.hint or ""

    def sign_in_password(self, password: str) -> bool:
        """
        Complete sign-in for an account protected by Telegram 2FA.

        The password is used only for this request and is never persisted.
        """
        if not password:
            raise RuntimeError("Telegram password is required")

        client = self._get_client()
        try:
            _run(client.sign_in(**{"password": password}))
            self._connected = True
            log.info("Telegram: signed in successfully with two-step verification")
            return True
        except Exception as exc:
            log.error("Telegram: two-step verification failed: %s", exc)
            raise RuntimeError(f"Two-step verification failed: {exc}") from exc

    def disconnect(self) -> None:
        """Disconnect the client and remove the session file."""
        if self._client:
            try:
                _run(self._client.disconnect())
            except Exception:
                pass
        self._connected = False
        self._client = None
        session_file = Path(str(self._session_path) + ".session")
        if session_file.exists():
            session_file.unlink()
            log.info("Telegram: session file removed")

    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Channel fetching
    # ------------------------------------------------------------------

    def fetch_channel(
        self,
        channel: str,
        source_id: int,
        limit: int = 100,
        since_hours: int = 24,
        min_text_length: int = 30,
        storage_dir: Optional[Path] = None,
    ) -> list[dict]:
        """
        Fetch recent messages from any Telegram chat the account can access.

        Supports public channels, private channels, and private groups — any
        chat that the authenticated account already has permission to read.

        If storage_dir is provided, media attachments (images, PDFs, documents)
        are downloaded and any extractable text is appended to raw_content so
        the full combined content enters the ingestion pipeline.

        Args:
            channel: Username (@channel), numeric chat ID, or Telethon entity.
            source_id: DB Source.id — stored in each returned dict.
            limit: Max messages to retrieve per call.
            since_hours: Only fetch messages newer than this many hours.
            min_text_length: Skip messages shorter than this (noise filtering).
            storage_dir: Directory to save downloaded media files (optional).

        Returns:
            List of dicts ready for IngestionService, keyed:
              external_id, raw_content, raw_metadata, fetched_at, has_media
        """
        if not self._connected:
            raise RuntimeError("Telegram client not connected")

        client = self._get_client()
        since_dt = datetime.utcnow() - timedelta(hours=since_hours)

        # Normalize common Telegram forms before resolving the entity.
        # This supports @usernames, t.me links, and numeric dialog IDs.
        channel_value = str(channel).strip()
        for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
            if channel_value.lower().startswith(prefix):
                channel_value = channel_value[len(prefix):]
                break
        channel_value = channel_value.split("?", 1)[0].split("/", 1)[0].strip()
        if channel_value.startswith("@"):
            channel_value = channel_value[1:]

        # Resolve channel identifier — supports int IDs for private chats.
        try:
            channel_entity = int(channel_value)
        except (TypeError, ValueError):
            channel_entity = channel_value

        async def _fetch():
            items = []
            # Resolve first so invalid usernames and inaccessible dialogs
            # produce a useful sync error instead of an empty result.
            entity = await client.get_entity(channel_entity)
            async for msg in client.iter_messages(
                entity, limit=limit, offset_date=None, reverse=False
            ):
                if msg.date.replace(tzinfo=None) < since_dt:
                    break

                text = (msg.text or msg.message or "").strip()
                media_path = None
                extracted_text = ""

                # Download and extract text from media attachments
                if msg.media and storage_dir:
                    try:
                        dl_path = await client.download_media(
                            msg, file=str(storage_dir) + "/"
                        )
                        if dl_path:
                            media_path = str(dl_path)
                            extracted_text = _extract_text_from_file(dl_path)
                    except Exception as exc:
                        log.warning(
                            "Media download failed for msg_id=%d channel=%s: %s",
                            msg.id, channel, exc,
                        )

                # Combine message text with any media-extracted text
                combined = text
                if extracted_text:
                    combined = f"{text}\n\n[From attachment:]\n{extracted_text}".strip()

                if len(combined) < min_text_length and not msg.media:
                    continue

                items.append({
                    "external_id": str(msg.id),
                    "raw_content": combined,
                    "raw_metadata": {
                        "channel": str(channel),
                        "channel_name": (
                            getattr(entity, "title", None)
                            or getattr(entity, "username", None)
                            or str(channel)
                        ),
                        "message_id": msg.id,
                        "date": msg.date.isoformat(),
                        "has_media": msg.media is not None,
                        "media_path": media_path,
                        "views": getattr(msg, "views", None),
                        "forwards": getattr(msg, "forwards", None),
                    },
                    "fetched_at": datetime.utcnow(),
                    "has_media": msg.media is not None,
                    "msg_id": msg.id,
                })
            return items

        return _run(_fetch(), timeout=120)

    def download_media_by_id(
        self, channel: str, msg_id: int, dest_dir: Path
    ) -> Optional[Path]:
        """
        Download the media attachment from a specific message.

        Returns:
            Path to the downloaded file, or None if download failed.
        """
        if not self._connected:
            return None

        client = self._get_client()
        dest_dir.mkdir(parents=True, exist_ok=True)

        async def _download():
            msg = await client.get_messages(channel, ids=msg_id)
            if not msg or not msg.media:
                return None
            path = await client.download_media(msg, file=str(dest_dir) + "/")
            return Path(path) if path else None

        try:
            return _run(_download(), timeout=120)
        except Exception as exc:
            log.error("Telegram: media download failed (msg_id=%d): %s", msg_id, exc)
            return None

    # ------------------------------------------------------------------
    # Dialog listing — all accessible chats
    # ------------------------------------------------------------------

    def list_dialogs(self, limit: int = 200) -> list[dict]:
        """
        List all chats the authenticated account can access.

        Returns public channels, private channels the account has joined,
        and private groups the account belongs to.  Does NOT attempt to
        access anything beyond the account's existing permissions.

        Returns:
            List of dicts: id, name, type ("channel"|"group"|"private"), username.
        """
        if not self._connected:
            raise RuntimeError("Telegram client not connected")

        client = self._get_client()

        async def _list():
            dialogs = []
            async for dialog in client.iter_dialogs(limit=limit):
                entity = dialog.entity
                first_name = getattr(entity, "first_name", None) or ""
                last_name = getattr(entity, "last_name", None) or ""
                fallback_name = " ".join(
                    part for part in (first_name, last_name) if part
                ).strip()
                name = (
                    dialog.name
                    or getattr(entity, "title", None)
                    or fallback_name
                    or getattr(entity, "username", None)
                    or str(dialog.id)
                )
                dialogs.append({
                    "id": str(dialog.id),
                    "name": name,
                    "type": (
                        "channel" if dialog.is_channel
                        else "group" if dialog.is_group
                        else "private"
                    ),
                    "username": getattr(entity, "username", None),
                    "members": getattr(entity, "participants_count", None),
                })
            return dialogs

        return _run(_list(), timeout=30)

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health_check_channel(self, channel: str) -> tuple[str, str]:
        """
        Verify access to a specific chat (channel, group, or private).

        Accepts username (@name) or numeric ID (as string or int).

        Returns:
            (status, message) where status is 'ok', 'error', or 'unknown'.
        """
        if not self._connected:
            return "error", "Telegram client not connected. Run setup first."
        client = self._get_client()
        try:
            # Support both username strings and numeric IDs
            try:
                entity_ref = int(channel)
            except (TypeError, ValueError):
                entity_ref = channel

            async def _check():
                entity = await client.get_entity(entity_ref)
                title = getattr(entity, "title", None) or getattr(entity, "username", str(channel))
                return "ok", f"Connected to '{title}'"
            return _run(_check(), timeout=15)
        except Exception as exc:
            return "error", str(exc)


# ---------------------------------------------------------------------------
# Singleton accessor — lazily created from app config
# ---------------------------------------------------------------------------
_service_instance: Optional[TelegramService] = None
_service_lock = threading.Lock()


def get_service() -> Optional[TelegramService]:
    """Return the process-wide Telethon service, creating it from saved credentials."""
    global _service_instance

    from flask import current_app
    from ..models.api_key import ApiKeySetting

    api_id = (
        ApiKeySetting.get("telegram_user", "api_id")
        or current_app.config.get("TELEGRAM_API_ID")
        or os.environ.get("TELEGRAM_API_ID")
    )
    api_hash = (
        ApiKeySetting.get("telegram_user", "api_hash")
        or current_app.config.get("TELEGRAM_API_HASH")
        or os.environ.get("TELEGRAM_API_HASH")
    )

    if not api_id or not api_hash:
        return None

    try:
        api_id = int(api_id)
    except (TypeError, ValueError):
        log.error("Telegram API ID must be an integer")
        return None

    session_dir = Path(current_app.config["SESSIONS_DIR"])
    session_dir.mkdir(parents=True, exist_ok=True)
    session_path = session_dir / "scholarmind"

    with _service_lock:
        if (
            _service_instance is None
            or _service_instance._api_id != api_id
            or _service_instance._api_hash != str(api_hash)
        ):
            if _service_instance is not None:
                try:
                    _service_instance.disconnect()
                except Exception:
                    pass
            _service_instance = TelegramService(api_id, str(api_hash), session_path)
            # Restore an existing authorized session if one is available.
            _service_instance.connect_saved_session()

    return _service_instance


def reset_service() -> None:
    """Force the singleton to be recreated on next get_service() call."""
    global _service_instance
    with _service_lock:
        _service_instance = None
