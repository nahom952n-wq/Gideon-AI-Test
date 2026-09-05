"""
TelegramBotUser model — maps a Telegram user to a Gideon ChatSession.

One row is created the first time a Telegram user messages the bot.
Subsequent messages from the same user reuse the same ChatSession so
conversation history is preserved across restarts.
"""

from datetime import datetime
from ..extensions import db


class TelegramBotUser(db.Model):
    """Maps a Telegram user_id to a persistent Gideon ChatSession."""

    __tablename__ = "telegram_bot_users"

    id             = db.Column(db.Integer, primary_key=True)
    telegram_id    = db.Column(db.BigInteger, nullable=False, unique=True, index=True)
    first_name     = db.Column(db.String(200), nullable=True)
    username       = db.Column(db.String(200), nullable=True)
    chat_session_id = db.Column(
        db.Integer, db.ForeignKey("chat_sessions.id"), nullable=True
    )
    created_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    chat_session = db.relationship("ChatSession")

    def __repr__(self) -> str:
        return (
            f"<TelegramBotUser telegram_id={self.telegram_id} "
            f"session={self.chat_session_id}>"
        )

    # ── Class helpers ─────────────────────────────────────────────────────

    @classmethod
    def get_or_create(cls, telegram_id: int, first_name: str = "", username: str = ""):
        """
        Return the TelegramBotUser for *telegram_id*, creating one if needed.
        Also creates a linked ChatSession if one does not exist yet.

        Must be called inside a Flask app context with an active db.session.
        """
        from ..models.chat import ChatSession
        from ..extensions import db as _db

        user = cls.query.filter_by(telegram_id=telegram_id).first()

        if user is None:
            session = ChatSession(title=f"Telegram: {first_name or telegram_id}")
            _db.session.add(session)
            _db.session.flush()  # assign session.id

            user = cls(
                telegram_id     = telegram_id,
                first_name      = first_name,
                username        = username,
                chat_session_id = session.id,
            )
            _db.session.add(user)
            _db.session.flush()
        else:
            # Keep display fields fresh
            user.first_name  = first_name or user.first_name
            user.username    = username   or user.username
            user.last_seen_at = datetime.utcnow()

            # Safety: recreate session if it was deleted
            if user.chat_session_id is None:
                session = ChatSession(title=f"Telegram: {first_name or telegram_id}")
                _db.session.add(session)
                _db.session.flush()
                user.chat_session_id = session.id

        return user
