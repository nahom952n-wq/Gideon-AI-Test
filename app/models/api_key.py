"""
ApiKeySetting — encrypted API key storage for Gideon.

Priority for key resolution: Database → .env → Flask config
Encryption: Fernet (from `cryptography` package), derived from SECRET_KEY.
Falls back to base64 if `cryptography` is not installed (not secure — install it).
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Optional

from ..extensions import db

log = logging.getLogger("scholarmind.api_keys")

# ── Provider registry ─────────────────────────────────────────────────────────

PROVIDERS = ["gemini", "openai", "anthropic", "grok", "local_ai"]

PROVIDER_META: dict[str, dict] = {
    "gemini": {
        "label":    "Google Gemini",
        "icon":     "bi-google",
        "color":    "primary",
        "key_env":  "GEMINI_API_KEY",
        "key_label":"API Key",
        "extra_fields": [
            {"name": "model", "label": "Model", "env": "GEMINI_MODEL",
             "placeholder": "gemini-3.5-flash",
             "recommended": [
                 "gemini-3.5-flash",
                 "gemini-3.5-flash-lite",
                 "gemini-3.1-flash-lite",
                 "gemini-3-flash-preview",
                 "gemini-2.5-flash",
             ]},
        ],
    },
    "openai": {
        "label":    "OpenAI (ChatGPT)",
        "icon":     "bi-stars",
        "color":    "success",
        "key_env":  "OPENAI_API_KEY",
        "key_label":"API Key",
        "extra_fields": [
            {"name": "model", "label": "Model", "env": "OPENAI_MODEL",
             "placeholder": "gpt-4o-mini",
             "recommended": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"]},
        ],
    },
    "anthropic": {
        "label":    "Anthropic (Claude)",
        "icon":     "bi-cpu",
        "color":    "warning",
        "key_env":  "ANTHROPIC_API_KEY",
        "key_label":"API Key",
        "extra_fields": [
            {"name": "model", "label": "Model", "env": "ANTHROPIC_MODEL",
             "placeholder": "claude-3-5-sonnet-20241022",
             "recommended": [
                 "claude-3-5-sonnet-20241022",
                 "claude-3-opus-20240229",
                 "claude-3-haiku-20240307",
             ]},
        ],
    },
    "grok": {
        "label":    "xAI (Grok)",
        "icon":     "bi-lightning-charge",
        "color":    "danger",
        "key_env":  "GROK_API_KEY",
        "key_label":"API Key",
        "extra_fields": [
            {"name": "model", "label": "Model", "env": "GROK_MODEL",
             "placeholder": "grok-2",
             "recommended": ["grok-2", "grok-beta", "grok-2-mini"]},
        ],
    },
    "local_ai": {
        "label":    "Local AI (Ollama / LM Studio)",
        "icon":     "bi-pc-display",
        "color":    "secondary",
        "key_env":  "LOCAL_AI_URL",
        "key_label":"Endpoint URL",
        "extra_fields": [
            {"name": "model", "label": "Model", "env": "LOCAL_AI_MODEL",
             "placeholder": "llama3",
             "recommended": ["llama3", "mistral", "phi3", "codellama", "gemma2"],
             "allow_custom": True},
        ],
    },
}

# ── Fernet helper ─────────────────────────────────────────────────────────────

def _get_fernet():
    """
    Return a Fernet instance keyed from Flask's SECRET_KEY.
    Returns None if `cryptography` is not installed.
    """
    try:
        from cryptography.fernet import Fernet
        import hashlib
        from flask import current_app

        secret = current_app.config.get("SECRET_KEY", "")
        if isinstance(secret, str):
            secret = secret.encode()
        # Fernet needs exactly 32 url-safe base64 bytes
        key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
        return Fernet(key)
    except ImportError:
        log.warning(
            "cryptography package not installed — API keys are stored as plain base64. "
            "Run: pip install cryptography"
        )
        return None
    except Exception as exc:
        log.error("Failed to initialise Fernet: %s", exc)
        return None


def _encrypt(value: str) -> str:
    """Encrypt a string value. Returns ciphertext or base64 fallback."""
    f = _get_fernet()
    if f:
        return f.encrypt(value.encode()).decode()
    # fallback: base64 (not secure, but prevents plaintext storage)
    return base64.b64encode(value.encode()).decode()


def _decrypt(stored: str) -> str:
    """Decrypt a stored value. Returns plaintext or raises ValueError."""
    f = _get_fernet()
    if f:
        try:
            return f.decrypt(stored.encode()).decode()
        except Exception:
            # May be a legacy base64 value — try that
            pass
    # fallback: base64
    try:
        return base64.b64decode(stored.encode()).decode()
    except Exception as exc:
        raise ValueError(f"Cannot decrypt stored value: {exc}") from exc


# ── ORM model ─────────────────────────────────────────────────────────────────

class ApiKeySetting(db.Model):
    """
    Stores one setting per (provider, key_name) pair.

    Examples:
        provider="gemini",    key_name="api_key" → the Gemini API key
        provider="gemini",    key_name="model"   → preferred model name
        provider="__routing__", key_name="capability_map" → JSON routing prefs
        provider="telegram_bot", key_name="token"  → Telegram bot token
        provider="telegram_bot", key_name="enabled" → "true" / "false"
    """

    __tablename__ = "api_key_settings"

    id         = db.Column(db.Integer, primary_key=True)
    provider   = db.Column(db.String(64),  nullable=False)
    key_name   = db.Column(db.String(64),  nullable=False, default="api_key")
    value_enc  = db.Column(db.Text,        nullable=False)  # always encrypted

    __table_args__ = (
        db.UniqueConstraint("provider", "key_name", name="uq_api_key_setting"),
    )

    def __repr__(self) -> str:
        return f"<ApiKeySetting provider={self.provider!r} key_name={self.key_name!r}>"

    # ── Class-level CRUD helpers ──────────────────────────────────────────

    @classmethod
    def get(cls, provider: str, key_name: str = "api_key") -> Optional[str]:
        """
        Return the decrypted value for (provider, key_name), or None.
        Never raises — logs errors and returns None on failure.
        """
        try:
            row = cls.query.filter_by(provider=provider, key_name=key_name).first()
            if row is None:
                return None
            return _decrypt(row.value_enc)
        except Exception as exc:
            log.error("ApiKeySetting.get(%r, %r) failed: %s", provider, key_name, exc)
            return None

    @classmethod
    def set(cls, provider: str, value: str, key_name: str = "api_key") -> "ApiKeySetting":
        """
        Upsert an encrypted setting.
        Does NOT commit — caller must call db.session.commit().
        """
        enc  = _encrypt(value)
        row  = cls.query.filter_by(provider=provider, key_name=key_name).first()
        if row:
            row.value_enc = enc
        else:
            row = cls(provider=provider, key_name=key_name, value_enc=enc)
            db.session.add(row)
        return row

    @classmethod
    def delete(cls, provider: str, key_name: str = "api_key") -> bool:
        """
        Delete a setting row.
        Does NOT commit — caller must call db.session.commit().
        Returns True if a row was deleted.
        """
        row = cls.query.filter_by(provider=provider, key_name=key_name).first()
        if row:
            db.session.delete(row)
            return True
        return False

    @classmethod
    def resolve(cls, provider: str, env_var: str, key_name: str = "api_key") -> Optional[str]:
        """
        Resolve a key with full priority chain: DB → env var → None.
        Use this in provider constructors so .env continues to work with zero changes.
        """
        db_val = cls.get(provider, key_name)
        if db_val:
            return db_val
        return os.environ.get(env_var) or None
