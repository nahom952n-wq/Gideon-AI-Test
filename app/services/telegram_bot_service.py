"""Telegram Bot API service for Gideon.

Runs a small dependency-light long-polling worker in a daemon thread.  The
userbot service remains separate and continues to use Telethon; this worker
uses Telegram's HTTPS Bot API directly through the requests dependency that
Gideon already uses elsewhere.

Supported commands
------------------
  /start          — welcome message
  /help           — usage guide
  /opportunities  — latest 5 active opportunities from the database
  /search <query> — keyword search across opportunities

Any other message is forwarded to ChatService.respond() — the same AI
pipeline used by the web chat interface.

Separation from the Telegram Userbot
-------------------------------------
This service manages a *bot* account (@YourBotName) via the Bot API.
The existing TelegramService/TelegramSource uses a *user account* via
MTProto (Telethon).  They share no code paths and cannot conflict.

Usage (from the Flask app factory)
-----------------------------------
    from app.services.telegram_bot_service import start_bot, stop_bot

    start_bot(token, flask_app)   # call after db.create_all()
    stop_bot()                    # call on shutdown (optional)
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Optional

import requests

log = logging.getLogger("scholarmind.telegram_bot")

# ── Module-level state ────────────────────────────────────────────────────────
_bot_thread: Optional[threading.Thread] = None
_running     = False
_bot_token: Optional[str] = None


# ── Public API ────────────────────────────────────────────────────────────────

def is_running() -> bool:
    """Return True if the bot thread is alive."""
    return _bot_thread is not None and _bot_thread.is_alive()


def start_bot(token: str, flask_app) -> None:
    """
    Start the Telegram bot in a background daemon thread.

    Safe to call multiple times — if the bot is already running it stops
    the old instance first.
    """
    global _bot_thread, _running, _bot_token

    if is_running():
        log.info("Bot already running — restarting with new token")
        stop_bot()

    _running = True
    _bot_token = token
    _bot_thread = threading.Thread(
        target=_thread_main,
        args=(token, flask_app),
        daemon=True,
        name="telegram-bot",
    )
    _bot_thread.start()
    log.info("Telegram bot thread started")


def stop_bot() -> None:
    """Signal the bot to stop and wait briefly for the thread to exit."""
    global _running, _bot_token

    _running = False
    _bot_token = None

    if _bot_thread is not None:
        _bot_thread.join(timeout=5)

    log.info("Telegram bot stopped")


# ── Thread entry point ────────────────────────────────────────────────────────

def _thread_main(token: str, flask_app) -> None:
    """Run the Bot API long-polling loop until stop_bot() is called."""
    try:
        _run_bot(token, flask_app)
    except Exception as exc:
        log.error("Bot thread crashed: %s", exc, exc_info=True)


def _run_bot(token: str, flask_app) -> None:
    """Poll Telegram updates and dispatch each message to Gideon's handlers."""
    api_url = f"https://api.telegram.org/bot{token}"
    offset = None
    log.info("Starting Telegram Bot API polling …")

    while _running:
        try:
            params = {"timeout": 25, "allowed_updates": ["message"]}
            if offset is not None:
                params["offset"] = offset
            response = requests.get(
                f"{api_url}/getUpdates", params=params, timeout=35
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                raise RuntimeError(payload.get("description", "Telegram polling failed"))

            for raw_update in payload.get("result", []):
                offset = raw_update["update_id"] + 1
                update = _Update.from_telegram(raw_update, api_url)
                if update.message is None or not update.message.text:
                    continue
                asyncio.run(_dispatch_update(update, flask_app))
        except requests.RequestException as exc:
            if _running:
                log.warning("Telegram polling request failed: %s", exc)
                threading.Event().wait(5)
        except Exception as exc:
            if _running:
                log.error("Telegram polling failed: %s", exc, exc_info=True)
                threading.Event().wait(5)

    log.info("Telegram Bot API polling stopped")


@dataclass
class _User:
    id: int
    first_name: str = ""
    username: str = ""


class _Chat:
    def __init__(self, chat_id: int, api_url: str):
        self.id = chat_id
        self._api_url = api_url

    async def send_action(self, action: str) -> None:
        requests.post(
            f"{self._api_url}/sendChatAction",
            json={"chat_id": self.id, "action": action},
            timeout=10,
        )


class _Message:
    def __init__(self, raw: dict, api_url: str):
        self.text = raw.get("text", "")
        self.chat = _Chat(raw["chat"]["id"], api_url)
        sender = raw.get("from", {})
        self.from_user = _User(
            id=sender.get("id", 0),
            first_name=sender.get("first_name", ""),
            username=sender.get("username", ""),
        )
        self._api_url = api_url

    async def reply_text(self, text: str, **kwargs) -> None:
        payload = {"chat_id": self.chat.id, "text": text}
        if kwargs.get("parse_mode"):
            payload["parse_mode"] = kwargs["parse_mode"]
        if kwargs.get("disable_web_page_preview"):
            payload["disable_web_page_preview"] = True
        requests.post(
            f"{self._api_url}/sendMessage", json=payload, timeout=15
        ).raise_for_status()


class _Update:
    def __init__(self, message: Optional[_Message]):
        self.message = message
        self.effective_user = message.from_user if message else None

    @classmethod
    def from_telegram(cls, raw: dict, api_url: str) -> "_Update":
        message = raw.get("message")
        return cls(_Message(message, api_url) if message else None)


@dataclass
class _Context:
    args: list[str]


async def _dispatch_update(update: _Update, flask_app) -> None:
    """Use the same handlers as the original Bot API implementation."""
    text = update.message.text.strip()
    command, *args = text.split()
    command = command.split("@", 1)[0].lower()
    handlers = {
        "/start": _cmd_start,
        "/help": _cmd_help,
        "/opportunities": _cmd_opportunities,
        "/search": _cmd_search,
    }
    handler = handlers.get(command, _handle_message)
    with flask_app.app_context():
        await handler(update, _Context(args))


# ── Handler factory ───────────────────────────────────────────────────────────

def _make_handler(flask_app, fn):
    """
    Wrap an async handler so it runs inside a Flask application context.
    SQLAlchemy operations require an active app context.
    """
    async def wrapper(update, context):
        with flask_app.app_context():
            await fn(update, context)
    return wrapper


# ── Helpers ───────────────────────────────────────────────────────────────────

FOOTER = "\n\n_Powered by Gideon • Reply to continue conversation_"

HELP_TEXT = """\
🎓 *Gideon Scholarship Assistant*

I can answer questions about scholarships, fellowships, grants, and other academic opportunities tracked in your Gideon database.

*Commands:*
/start — Welcome message
/help — This help message
/opportunities — Show the latest 5 opportunities
/search <keyword> — Quick keyword search

Or just *type any question* and I'll answer using the database + AI.

*Example questions:*
• "Are there any fully funded PhD scholarships in Germany?"
• "Tell me about Chevening"
• "What opportunities are closing this month?"
"""


def _get_or_create_user(tg_update):
    """Get/create TelegramBotUser and return (user, session_id)."""
    from ..models.telegram_bot_user import TelegramBotUser
    from ..extensions import db

    tg_user = tg_update.effective_user
    user = TelegramBotUser.get_or_create(
        telegram_id = tg_user.id,
        first_name  = tg_user.first_name or "",
        username    = tg_user.username   or "",
    )
    db.session.commit()
    return user, user.chat_session_id


def _save_messages(session_id: int, user_text: str, bot_text: str, source: str) -> None:
    """Persist the user message and bot reply to the shared ChatMessage table."""
    from ..models.chat import ChatMessage, ChatSession
    from ..extensions import db
    from datetime import datetime

    user_msg = ChatMessage(session_id=session_id, role="user",      content=user_text)
    bot_msg  = ChatMessage(session_id=session_id, role="assistant", content=bot_text, source=source)
    db.session.add_all([user_msg, bot_msg])

    session = ChatSession.query.get(session_id)
    if session:
        session.last_active_at = datetime.utcnow()
        if not session.title:
            session.title = user_text[:60]

    db.session.commit()


def _format_opportunity(opp) -> str:
    """Return a compact Markdown summary of an Opportunity."""
    parts = [f"*{opp.title or 'Untitled'}*"]
    if opp.organization:
        parts.append(f"🏛 {opp.organization}")
    if opp.country:
        parts.append(f"🌍 {opp.country}")
    if opp.deadline:
        parts.append(f"⏰ Deadline: {opp.deadline}")
    if opp.application_url:
        parts.append(f"🔗 [Apply here]({opp.application_url})")
    return "\n".join(parts)


# ── Command handlers ──────────────────────────────────────────────────────────

async def _cmd_start(update, context) -> None:
    user = update.effective_user
    name = user.first_name or "there"
    await update.message.reply_text(
        f"👋 Hi {name}! I'm *Gideon*, your personal scholarship and opportunity assistant.\n\n"
        "I search a curated database of scholarships, fellowships, grants, and more — "
        "just ask me anything.\n\n"
        "Type /help to see what I can do.",
        parse_mode="Markdown",
    )


async def _cmd_help(update, context) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def _cmd_opportunities(update, context) -> None:
    from ..models.opportunity import Opportunity

    opps = (
        Opportunity.query
        .filter_by(is_active=True, is_duplicate=False)
        .order_by(Opportunity.created_at.desc())
        .limit(5)
        .all()
    )

    if not opps:
        await update.message.reply_text(
            "No opportunities found in the database yet. "
            "Add some sources in the Gideon web interface first."
        )
        return

    lines = ["📋 *Latest 5 Opportunities*\n"]
    for i, opp in enumerate(opps, 1):
        lines.append(f"{i}. {_format_opportunity(opp)}\n")

    await update.message.reply_text(
        "\n".join(lines) + FOOTER,
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


async def _cmd_search(update, context) -> None:
    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        await update.message.reply_text(
            "Please provide a search term. Example:\n`/search Germany PhD`",
            parse_mode="Markdown",
        )
        return

    from ..models.opportunity import Opportunity
    from ..extensions import db as _db

    like = f"%{query}%"
    results = (
        Opportunity.query
        .filter(
            _db.or_(
                Opportunity.title.ilike(like),
                Opportunity.organization.ilike(like),
                Opportunity.country.ilike(like),
                Opportunity.summary.ilike(like),
                Opportunity.keywords_json.ilike(like),
            )
        )
        .filter_by(is_active=True, is_duplicate=False)
        .limit(5)
        .all()
    )

    if not results:
        await update.message.reply_text(
            f'No opportunities found matching "{query}". Try a different keyword.',
        )
        return

    lines = [f'🔍 *Results for "{query}"*\n']
    for i, opp in enumerate(results, 1):
        lines.append(f"{i}. {_format_opportunity(opp)}\n")

    await update.message.reply_text(
        "\n".join(lines) + FOOTER,
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


async def _handle_message(update, context) -> None:
    """Route a plain text message through ChatService."""
    user_text = update.message.text.strip()
    if not user_text:
        return

    # Show typing indicator while the AI thinks
    await update.message.chat.send_action("typing")

    tg_user, session_id = _get_or_create_user(update)

    try:
        from ..services.chat_service import ChatService
        svc = ChatService()
        response_text, source = svc.respond(user_text, session_id)
    except Exception as exc:
        log.error("ChatService error in bot handler: %s", exc, exc_info=True)
        response_text = (
            "Sorry, I ran into an error processing your message. "
            "Please try again or check the AI provider settings."
        )
        source = "error"

    _save_messages(session_id, user_text, response_text, source)

    await update.message.reply_text(
        response_text + FOOTER,
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )
