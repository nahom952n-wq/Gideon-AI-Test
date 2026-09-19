"""Dashboard routes — main overview page with Focus Mode support."""

import logging
from flask import Blueprint, render_template, request, session, current_app
from ..models import Application, Source, RawItem
from ..models.opportunity import Opportunity, OpportunityType
from ..extensions import db
from .auth import login_required
from sqlalchemy import func

bp = Blueprint("dashboard", __name__)
log = logging.getLogger("scholarmind.app")


def _get_focus() -> str:
    """
    Resolve the active dashboard focus.

    Priority: session (set via Settings page) > config default > "mixed".
    """
    focus = session.get(
        "dashboard_focus",
        current_app.config.get("DASHBOARD_FOCUS", "mixed"),
    )
    valid = ["mixed"] + OpportunityType.ALL
    return focus if focus in valid else "mixed"


def _has_key(provider: str, env_name: str) -> bool:
    """True when an AI key exists in the database or the environment."""
    try:
        from ..models.api_key import ApiKeySetting

        provider = {"claude": "anthropic"}.get(provider, provider)
        if ApiKeySetting.get(provider):
            return True
    except Exception:
        pass
    import os

    return bool(os.environ.get(env_name) or current_app.config.get(env_name))


@bp.route("/")
@login_required
def index():
    """Main dashboard with overview statistics and Focus Mode."""
    focus = _get_focus()

    # --- Stats ---
    base_q = Opportunity.query.filter_by(is_active=True, is_duplicate=False)
    if focus != "mixed":
        focused_q = base_q.filter_by(opportunity_type=focus)
    else:
        focused_q = base_q

    total_opportunities = db.session.query(func.count(Opportunity.id)).scalar() or 0
    active_opportunities = focused_q.with_entities(func.count(Opportunity.id)).scalar() or 0

    total_applications = db.session.query(func.count(Application.id)).scalar() or 0
    active_sources = (
        db.session.query(func.count(Source.id))
        .filter(Source.is_active == True)
        .scalar() or 0
    )
    pending_items = (
        db.session.query(func.count(RawItem.id))
        .filter(RawItem.processing_status == "pending")
        .scalar() or 0
    )

    # --- Type breakdown (for display when focus == "mixed") ---
    type_counts = {}
    if focus == "mixed":
        rows = (
            db.session.query(Opportunity.opportunity_type, func.count(Opportunity.id))
            .filter(Opportunity.is_active == True, Opportunity.is_duplicate == False)
            .group_by(Opportunity.opportunity_type)
            .all()
        )
        type_counts = {r[0]: r[1] for r in rows}

    # --- Recent opportunities (focused or all) ---
    recent = (
        focused_q
        .order_by(Opportunity.created_at.desc())
        .limit(8)
        .all()
    )

    # --- Upcoming deadlines ---
    from datetime import date
    upcoming = (
        base_q.filter(Opportunity.deadline != None, Opportunity.deadline >= date.today())
        .order_by(Opportunity.deadline.asc())
        .limit(6)
        .all()
    )

    # --- System status ---
    system = {
        "telegram": bool(current_app.config.get("TELEGRAM_API_ID") and current_app.config.get("TELEGRAM_API_HASH")),
        "ai_keys": [
            name for name, key in (
                ("Gemini", "GEMINI_API_KEY"),
                ("OpenAI", "OPENAI_API_KEY"),
                ("Claude", "ANTHROPIC_API_KEY"),
                ("Grok", "GROK_API_KEY"),
            ) if _has_key(name.lower(), key)
        ],
        "pending_items": pending_items,
        "active_sources": active_sources,
    }

    stats = {
        "total_opportunities":  total_opportunities,
        "active_opportunities": active_opportunities,
        "total_applications":   total_applications,
        "active_sources":       active_sources,
        "pending_items":        pending_items,
        "focus":                focus,
    }

    return render_template(
        "dashboard/index.html",
        stats=stats,
        recent_opportunities=recent,
        type_counts=type_counts,
        focus=focus,
        opportunity_types=OpportunityType.ALL,
        opportunity_icons=OpportunityType.ICONS,
        opportunity_colors=OpportunityType.COLORS,
        opportunity_labels=OpportunityType.LABELS,
        upcoming=upcoming,
        system=system,
    )
