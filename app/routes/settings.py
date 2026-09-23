"""Settings, AI provider, and Telegram controls for Gideon."""

from __future__ import annotations

import json
import logging
import os

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..config import DEFAULT_GEMINI_MODEL
from ..models.api_key import ApiKeySetting, PROVIDERS, PROVIDER_META
from .auth import admin_required, current_user

bp = Blueprint("settings", __name__, url_prefix="/settings")
log = logging.getLogger("scholarmind.settings")


def _provider_value(provider: str, key_name: str, config_name: str, default=None):
    """Resolve a saved setting first, then the environment-backed config."""
    return ApiKeySetting.get(provider, key_name) or current_app.config.get(
        config_name, default
    )


def _probe_telegram(cfg: dict) -> dict:
    api_id = cfg.get("TELEGRAM_API_ID")
    api_hash = cfg.get("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        missing = [name for name in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH") if not cfg.get(name)]
        return {
            "status": "missing_key",
            "detail": f"Missing: {', '.join(missing)}",
            "vars": ["TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_PHONE"],
        }
    try:
        from ..services.telegram_service import get_service

        service = get_service(current_user().id)
        connected = service is not None and service.is_connected()
        return {
            "status": "connected" if connected else "connection_failed",
            "detail": "Session active" if connected else "Credentials set — no active session",
            "phone": cfg.get("TELEGRAM_PHONE") or "not set",
            "vars": ["TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_PHONE"],
        }
    except Exception as exc:
        return {
            "status": "config_error",
            "detail": str(exc),
            "vars": ["TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_PHONE"],
        }


def _probe_local_ai(cfg: dict) -> dict:
    url = _provider_value("local_ai", "api_key", "LOCAL_AI_URL")
    model = _provider_value("local_ai", "model", "LOCAL_AI_MODEL", "qwen2.5")
    if not url:
        return {
            "status": "missing_key",
            "detail": "LOCAL_AI_URL not set",
            "vars": ["LOCAL_AI_URL", "LOCAL_AI_MODEL"],
        }
    try:
        from ..ai.providers.local_ai import LocalAIProvider

        available = LocalAIProvider(base_url=url, model=model).is_available()
        return {
            "status": "connected" if available else "connection_failed",
            "detail": f"{url} ({model})" if available else f"Could not reach {url}",
            "url": url,
            "model": model,
            "vars": ["LOCAL_AI_URL", "LOCAL_AI_MODEL"],
        }
    except Exception as exc:
        return {
            "status": "config_error",
            "detail": str(exc),
            "vars": ["LOCAL_AI_URL", "LOCAL_AI_MODEL"],
        }


def _probe_key_provider(provider: str, config_key: str, config_model: str, default_model: str) -> dict:
    key = _provider_value(provider, "api_key", config_key)
    model = _provider_value(provider, "model", config_model, default_model)
    if not key:
        return {
            "status": "missing_key",
            "detail": f"{config_key} not set",
            "vars": [config_key, config_model],
        }
    try:
        if provider == "gemini":
            from ..ai.providers.gemini import GeminiProvider

            available = GeminiProvider(api_key=key, model=model).is_available()
        elif provider == "openai":
            from ..ai.providers.openai_provider import OpenAIProvider

            available = OpenAIProvider(api_key=key, model=model).is_available()
        elif provider == "anthropic":
            from ..ai.providers.anthropic_provider import AnthropicProvider

            available = AnthropicProvider(api_key=key, model=model).is_available()
        elif provider == "grok":
            from ..ai.providers.grok_provider import GrokProvider

            available = GrokProvider(api_key=key, model=model).is_available()
        else:
            available = bool(key)
        return {
            "status": "connected" if available else "config_error",
            "detail": f"Model: {model}",
            "model": model,
            "vars": [config_key, config_model],
        }
    except Exception as exc:
        return {
            "status": "config_error",
            "detail": str(exc),
            "vars": [config_key, config_model],
        }


def _probe_telegram_bot(cfg: dict) -> dict:
    from ..services import telegram_bot_service

    token = ApiKeySetting.get("telegram_bot", "token") or cfg.get("TELEGRAM_BOT_TOKEN")
    enabled = (
        ApiKeySetting.get("telegram_bot", "enabled")
        or cfg.get("TELEGRAM_BOT_ENABLED", "false")
    ).lower() == "true"
    running = telegram_bot_service.is_running()
    if not token:
        return {
            "status": "missing_key",
            "detail": "No bot token saved yet.",
            "running": False,
            "enabled": enabled,
        }
    if not enabled:
        return {
            "status": "disabled",
            "detail": "Bot is disabled.",
            "running": False,
            "enabled": False,
        }
    return {
        "status": "connected" if running else "connection_failed",
        "detail": "Polling for messages" if running else "Enabled but not running",
        "running": running,
        "enabled": True,
    }


def _all_probes(cfg: dict) -> dict:
    return {
        "telegram": _probe_telegram(cfg),
        "local_ai": _probe_local_ai(cfg),
        "gemini": _probe_key_provider(
            "gemini", "GEMINI_API_KEY", "GEMINI_MODEL", DEFAULT_GEMINI_MODEL
        ),
        "openai": _probe_key_provider(
            "openai", "OPENAI_API_KEY", "OPENAI_MODEL", "gpt-4o-mini"
        ),
        "anthropic": _probe_key_provider(
            "anthropic",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_MODEL",
            "claude-3-5-sonnet-20241022",
        ),
        "grok": _probe_key_provider("grok", "GROK_API_KEY", "GROK_MODEL", "grok-2"),
    }


def _api_key_page_data(cfg: dict) -> dict:
    providers = []
    for provider in PROVIDERS:
        meta = PROVIDER_META[provider]
        stored_key = ApiKeySetting.get(provider)
        env_key = os.environ.get(meta["key_env"], "") or cfg.get(meta["key_env"], "")
        extra_values = {}
        for field in meta.get("extra_fields", []):
            extra_values[field["name"]] = (
                ApiKeySetting.get(provider, field["name"])
                or os.environ.get(field["env"], "")
                or cfg.get(field["env"], "")
            )
        providers.append(
            {
                "id": provider,
                "label": meta["label"],
                "icon": meta["icon"],
                "color": meta["color"],
                "key_label": meta["key_label"],
                "has_key": bool(stored_key or env_key),
                "source": "database" if stored_key else ("env" if env_key else "none"),
                "extra_fields": meta.get("extra_fields", []),
                "extra_values": extra_values,
            }
        )

    routing = {}
    try:
        saved = ApiKeySetting.get("__routing__", "capability_map")
        routing = json.loads(saved) if saved else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        log.warning("Saved capability routing could not be decoded")

    capabilities = list(cfg.get("CAPABILITY_MAP", {}).keys())
    capability_map = {
        capability: routing.get(capability, cfg["CAPABILITY_MAP"].get(capability))
        for capability in capabilities
    }
    return {
        "providers": providers,
        "capabilities": capabilities,
        "capability_map": capability_map,
        "all_providers": ["local", "gemini", "openai", "anthropic", "grok"],
    }


@bp.route("/")
@admin_required
def index():
    cfg = current_app.config
    pipeline_cfg = {
        "processing_version": cfg.get("PROCESSING_VERSION", "3.0"),
        "enrichment_rate": cfg.get("AI_ENRICHMENT_RATE", 5),
        "confidence_threshold": cfg.get("LOCAL_AI_CONFIDENCE_THRESHOLD", 0.60),
        "focus_mode": session.get("dashboard_focus", cfg.get("DASHBOARD_FOCUS", "mixed")),
        "capability_map": cfg.get("CAPABILITY_MAP", {}),
    }
    return render_template(
        "settings/index.html",
        integrations=_all_probes(cfg),
        telegram_bot=_probe_telegram_bot(cfg),
        pipeline_cfg=pipeline_cfg,
        telegram_user=telegram_user_values(cfg),
        telegram_bot_token_saved=bool(ApiKeySetting.get("telegram_bot", "token") or cfg.get("TELEGRAM_BOT_TOKEN")),
        **_api_key_page_data(cfg),
    )


@bp.route("/integrations/probe")
@admin_required
def probe_integration():
    name = request.args.get("name", "")
    if name == "telegram_bot":
        return jsonify(_probe_telegram_bot(current_app.config))
    probes = _all_probes(current_app.config)
    if name not in probes:
        return jsonify({"error": f"Unknown integration: {name}"}), 400
    return jsonify(probes[name])


@bp.route("/api-keys/save", methods=["POST"])
@admin_required
def save_api_key():
    from ..extensions import db

    provider = request.form.get("provider", "").strip()
    api_key = request.form.get("api_key", "").strip()
    model = request.form.get("model", "").strip()
    if provider not in PROVIDERS:
        flash("Unknown AI provider.", "danger")
        return redirect(url_for("settings.index") + "#tab-ai-providers")
    try:
        if api_key:
            ApiKeySetting.set(provider, api_key)
        else:
            ApiKeySetting.delete(provider)
        if model:
            ApiKeySetting.set(provider, model, "model")
        else:
            ApiKeySetting.delete(provider, "model")
        db.session.commit()
        flash(f"{'Saved' if api_key else 'Cleared'} settings for {provider}.", "success")
    except Exception as exc:
        db.session.rollback()
        log.error("Could not save settings for %s: %s", provider, exc)
        flash("Could not save provider settings.", "danger")
    return redirect(url_for("settings.index") + "#tab-ai-providers")


@bp.route("/api-keys/clear", methods=["POST"])
@admin_required
def clear_api_key():
    from ..extensions import db

    provider = request.form.get("provider", "").strip()
    if provider not in PROVIDERS:
        return jsonify({"success": False, "error": "Unknown provider"}), 400
    try:
        ApiKeySetting.delete(provider)
        ApiKeySetting.delete(provider, "model")
        db.session.commit()
        return jsonify({"success": True})
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 500


@bp.route("/api-keys/test", methods=["POST"])
@admin_required
def test_api_key():
    data = request.get_json(silent=True) or {}
    provider = str(data.get("provider", "")).strip()
    api_key = str(data.get("api_key", "")).strip()
    model = str(data.get("model", "")).strip()
    if provider not in PROVIDERS or not api_key:
        return jsonify({"ok": False, "message": "Choose a provider and enter a value to test."}), 400
    try:
        instance = _build_test_provider(provider, api_key, model)
        if provider == "local_ai":
            available = instance.is_available()
            message = "Endpoint is reachable." if available else "Endpoint could not be reached."
            return jsonify({"ok": available, "message": message})
        response = instance.complete(
            "Reply with only the word PONG.",
            system="You are a connection test. Reply with only PONG.",
        )
        return jsonify(
            {
                "ok": response.success,
                "message": f"Connected with {instance.model}."
                if response.success
                else (response.error or "Provider test failed."),
            }
        )
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)})


def _build_test_provider(provider: str, value: str, model: str):
    if provider == "gemini":
        from ..ai.providers.gemini import GeminiProvider

        return GeminiProvider(api_key=value, model=model or DEFAULT_GEMINI_MODEL)
    if provider == "openai":
        from ..ai.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(api_key=value, model=model or "gpt-4o-mini")
    if provider == "anthropic":
        from ..ai.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            api_key=value, model=model or "claude-3-5-sonnet-20241022"
        )
    if provider == "grok":
        from ..ai.providers.grok_provider import GrokProvider

        return GrokProvider(api_key=value, model=model or "grok-2")
    if provider == "local_ai":
        from ..ai.providers.local_ai import LocalAIProvider

        return LocalAIProvider(base_url=value, model=model or "llama3")
    raise ValueError("Unknown provider")


@bp.route("/capability-map/save", methods=["POST"])
def save_capability_map():
    from ..extensions import db

    routing = {
        capability: request.form.get(f"capability_{capability}", "").strip()
        for capability in current_app.config.get("CAPABILITY_MAP", {})
    }
    routing = {key: value for key, value in routing.items() if value}
    try:
        ApiKeySetting.set("__routing__", json.dumps(routing), "capability_map")
        db.session.commit()
        flash("AI routing preferences saved.", "success")
    except Exception as exc:
        db.session.rollback()
        log.error("Could not save routing: %s", exc)
        flash("Could not save AI routing preferences.", "danger")
    return redirect(url_for("settings.index") + "#tab-ai-providers")


@bp.route("/telegram-bot/save", methods=["POST"])
def save_telegram_bot():
    from ..extensions import db
    from ..services import telegram_bot_service

    token = request.form.get("bot_token", "").strip()
    enabled = request.form.get("enabled", "false").lower()
    try:
        if token:
            ApiKeySetting.set("telegram_bot", token, "token")
        ApiKeySetting.set("telegram_bot", "true" if enabled == "true" else "false", "enabled")
        db.session.commit()
        resolved_token = token or ApiKeySetting.get("telegram_bot", "token")
        if enabled == "true" and resolved_token:
            telegram_bot_service.start_bot(
                resolved_token, current_app._get_current_object()
            )
            flash("Telegram bot enabled and started.", "success")
        else:
            telegram_bot_service.stop_bot()
            flash("Telegram bot disabled.", "info")
    except Exception as exc:
        db.session.rollback()
        log.error("Could not save Telegram bot settings: %s", exc)
        flash("Could not save Telegram bot settings.", "danger")
    return redirect(url_for("settings.index") + "#tab-telegram-bot")


@bp.route("/telegram-bot/test", methods=["POST"])
def test_telegram_bot():
    data = request.get_json(silent=True) or {}
    token = str(data.get("token", "")).strip()
    if not token:
        return jsonify({"ok": False, "message": "Enter a bot token to test."})
    try:
        import requests

        response = requests.get(
            f"https://api.telegram.org/bot{token}/getMe", timeout=8
        )
        payload = response.json()
        if payload.get("ok"):
            bot = payload["result"]
            return jsonify(
                {
                    "ok": True,
                    "message": f"Connected: @{bot.get('username', 'bot')}",
                }
            )
        return jsonify({"ok": False, "message": payload.get("description", "Invalid token.")})
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)})


@bp.route("/focus", methods=["POST"])
def set_focus():
    from ..models.opportunity import OpportunityType

    focus = request.form.get("focus", "mixed")
    if focus not in ["mixed"] + OpportunityType.ALL:
        focus = "mixed"
    session["dashboard_focus"] = focus
    flash(f"Dashboard focus set to: {focus.title()}", "success")
    return redirect(request.referrer or url_for("dashboard.index"))


# ── Telegram user (userbot) credentials ───────────────────────────────────────

TELEGRAM_USER_FIELDS = {
    "api_id": "TELEGRAM_API_ID",
    "api_hash": "TELEGRAM_API_HASH",
    "phone": "TELEGRAM_PHONE",
}


def telegram_user_values(cfg) -> dict:
    """Resolve Telegram userbot credentials: database → environment/config."""
    values = {}
    for name, env in TELEGRAM_USER_FIELDS.items():
        values[name] = (
            ApiKeySetting.get("telegram_user", name)
            or os.environ.get(env, "")
            or (cfg.get(env) or "")
        )
    return values


@bp.before_app_request
def _apply_saved_telegram_credentials():
    """Push database-saved Telegram credentials into the app config once."""
    if current_app.config.get("_TELEGRAM_USER_APPLIED"):
        return
    try:
        for name, env in TELEGRAM_USER_FIELDS.items():
            saved = ApiKeySetting.get("telegram_user", name)
            if saved:
                current_app.config[env] = saved
        current_app.config["_TELEGRAM_USER_APPLIED"] = True
    except Exception:  # database may not be ready yet
        pass


@bp.route("/telegram-user/save", methods=["POST"])
def save_telegram_user():
    from ..extensions import db

    try:
        for name, env in TELEGRAM_USER_FIELDS.items():
            value = request.form.get(name, "").strip()
            if value:
                ApiKeySetting.set("telegram_user", value, name)
                current_app.config[env] = value
        db.session.commit()
        flash("Telegram credentials saved.", "success")
    except Exception as exc:
        db.session.rollback()
        log.error("Could not save Telegram credentials: %s", exc)
        flash("Could not save Telegram credentials.", "danger")
    return redirect(url_for("settings.index") + "#tab-telegram-account")
