"""
SQLAlchemy ORM models for Gideon.

Import all models here so db.create_all() discovers them in the app factory.
"""

from .source import Source
from .raw_item import RawItem
from .media_attachment import MediaAttachment
from .scholarship import Scholarship
from .opportunity import Opportunity, OpportunityType
from .user_profile import UserProfile
from .match_score import MatchScore
from .application import Application, ApplicationStatus, StatusHistory
from .notification import NotificationLog
from .chat import ChatSession, ChatMessage
from .api_key import ApiKeySetting, PROVIDERS, PROVIDER_META
from .telegram_bot_user import TelegramBotUser
from .user import User

__all__ = [
    "Source",
    "RawItem",
    "MediaAttachment",
    "Scholarship",
    "Opportunity",
    "OpportunityType",
    "UserProfile",
    "MatchScore",
    "Application",
    "ApplicationStatus",
    "StatusHistory",
    "NotificationLog",
    "ChatSession",
    "ChatMessage",
    "ApiKeySetting",
    "PROVIDERS",
    "PROVIDER_META",
    "TelegramBotUser",
    "User",
]
