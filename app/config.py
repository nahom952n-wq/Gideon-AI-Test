"""
Configuration classes for ScholarMind AI.

Uses python-dotenv to load secrets from .env — never hardcode credentials.
"""

import os
import secrets
import sys
from pathlib import Path
from dotenv import load_dotenv

if os.environ.get("GIDEON_RUNTIME_DIR"):
    BASE_DIR = Path(os.environ["GIDEON_RUNTIME_DIR"]).resolve()
elif getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
DEPRECATED_GEMINI_MODELS = {"gemini-1.5-flash", "gemini-2.5-flash"}


class BaseConfig:
    """Shared settings for all environments."""

    # Production requires an explicit secret. For local development, persist a
    # generated secret so encrypted API keys remain decryptable across restarts.
    _secret_file = BASE_DIR / ".flask_dev_secret"
    if os.environ.get("FLASK_SECRET_KEY"):
        SECRET_KEY: str = os.environ["FLASK_SECRET_KEY"]
    elif _secret_file.exists():
        SECRET_KEY: str = _secret_file.read_text(encoding="utf-8").strip()
    else:
        SECRET_KEY = secrets.token_urlsafe(32)
        try:
            _secret_file.parent.mkdir(parents=True, exist_ok=True)
            _secret_file.write_text(SECRET_KEY, encoding="utf-8")
            try:
                _secret_file.chmod(0o600)
            except OSError:
                pass
        except OSError:
            pass

    BASE_DIR: Path = BASE_DIR
    DATA_DIR: Path = BASE_DIR / "data"
    STORAGE_DIR: Path = BASE_DIR / "storage"
    LOGS_DIR: Path = BASE_DIR / "logs"
    BACKUPS_DIR: Path = BASE_DIR / "backups"
    SESSIONS_DIR: Path = BASE_DIR / "storage" / "sessions"

    SQLALCHEMY_DATABASE_URI: str = f"sqlite:///{DATA_DIR / 'scholarmind.db'}"
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"
    SESSION_COOKIE_SECURE: bool = os.environ.get("SCHOLARMIND_SECURE_COOKIES", "false").lower() == "true"
    START_BACKGROUND_SERVICES: bool = os.environ.get("SCHOLARMIND_START_BACKGROUND_SERVICES", "true").lower() == "true"
    SQLALCHEMY_ENGINE_OPTIONS: dict = {
        "connect_args": {"check_same_thread": False},
        "pool_size": 5,
        "pool_timeout": 20,
    }

    # --- AI providers ---
    ACTIVE_AI_PROVIDER: str = os.environ.get("ACTIVE_AI_PROVIDER", "gemini")
    GEMINI_API_KEY: str | None = os.environ.get("GEMINI_API_KEY")
    _configured_gemini_model = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    GEMINI_MODEL: str = (
        DEFAULT_GEMINI_MODEL
        if _configured_gemini_model in DEPRECATED_GEMINI_MODELS
        else _configured_gemini_model
    )
    OPENAI_API_KEY: str | None = os.environ.get("OPENAI_API_KEY")
    OPENAI_MODEL: str = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    ANTHROPIC_API_KEY: str | None = os.environ.get("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL: str = os.environ.get(
        "ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"
    )
    GROK_API_KEY: str | None = os.environ.get("GROK_API_KEY")
    GROK_MODEL: str = os.environ.get("GROK_MODEL", "grok-2")

    # --- Telegram Bot API (separate from the Telethon userbot) ---
    TELEGRAM_BOT_TOKEN: str | None = os.environ.get("TELEGRAM_BOT_TOKEN")
    TELEGRAM_BOT_ENABLED: str = os.environ.get("TELEGRAM_BOT_ENABLED", "false")

    # --- Local OpenAI-compatible inference (Ollama, LM Studio, etc.) ---
    LOCAL_AI_URL: str | None = os.environ.get("LOCAL_AI_URL")
    LOCAL_AI_MODEL: str = os.environ.get("LOCAL_AI_MODEL", "qwen2.5")
    LOCAL_AI_CONFIDENCE_THRESHOLD: float = float(
        os.environ.get("LOCAL_AI_CONFIDENCE_THRESHOLD", "0.60")
    )

    # --- Capability → provider mapping ---
    CAPABILITY_MAP: dict = {
        "summarization": os.environ.get("CAP_SUMMARIZATION_PROVIDER", "local"),
        "structured_extraction": os.environ.get("CAP_EXTRACTION_PROVIDER", "local"),
        "reasoning": os.environ.get("CAP_REASONING_PROVIDER", "gemini"),
        "translation": os.environ.get("CAP_TRANSLATION_PROVIDER", "local"),
        "classification": os.environ.get("CAP_CLASSIFICATION_PROVIDER", "local"),
        "vision_analysis": os.environ.get("CAP_VISION_PROVIDER", "gemini"),
        "chat": os.environ.get("CAP_CHAT_PROVIDER", "gemini"),
        "ocr": os.environ.get("CAP_OCR_PROVIDER", "gemini"),
    }

    # --- Pipeline ---
    PROCESSING_VERSION: str = "3.0"
    AI_ENRICHMENT_RATE: int = int(os.environ.get("AI_ENRICHMENT_RATE", "5"))

    # --- Dashboard Focus Mode ---
    DASHBOARD_FOCUS: str = os.environ.get("DASHBOARD_FOCUS", "mixed")

    # --- Notifications ---
    NOTIFICATION_SCORE_THRESHOLD: int = int(
        os.environ.get("NOTIFICATION_SCORE_THRESHOLD", "70")
    )

    # --- SMTP (optional) ---
    SMTP_HOST: str | None = os.environ.get("SMTP_HOST")
    SMTP_PORT: int = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USER: str | None = os.environ.get("SMTP_USER")
    SMTP_PASS: str | None = os.environ.get("SMTP_PASS")

    @classmethod
    def ensure_dirs(cls) -> None:
        """Create required runtime directories if they do not exist."""
        for d in [
            cls.DATA_DIR,
            cls.STORAGE_DIR,
            cls.LOGS_DIR,
            cls.BACKUPS_DIR,
            cls.SESSIONS_DIR,
            cls.STORAGE_DIR / "pdfs",
            cls.STORAGE_DIR / "images",
            cls.STORAGE_DIR / "documents",
            cls.STORAGE_DIR / "telegram",
        ]:
            d.mkdir(parents=True, exist_ok=True)


class DevelopmentConfig(BaseConfig):
    DEBUG: bool = True


class ProductionConfig(BaseConfig):
    DEBUG: bool = False

    @classmethod
    def ensure_dirs(cls) -> None:
        secret = os.environ.get("FLASK_SECRET_KEY")
        if not secret or len(secret) < 32:
            raise RuntimeError(
                "FLASK_SECRET_KEY must be set to a unique value of at least 32 characters in production."
            )
        cls.SECRET_KEY = secret
        super().ensure_dirs()


configs = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
}
