"""JSON API endpoints — consumed by dashboard charts and AJAX calls."""

import logging
from datetime import datetime
from flask import Blueprint, jsonify, request
from ..models import Application, Source, RawItem
from ..models.opportunity import Opportunity, OpportunityType
from ..extensions import db
from sqlalchemy import func

bp = Blueprint("api", __name__, url_prefix="/api")
log = logging.getLogger("scholarmind.app")


def _parse_datetime(value):
    if not value:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.utcnow()


def _get_or_create_telegram_source(source_data: dict, settings: dict) -> Source:
    channel_id = str(source_data.get("channel_id", "")).strip()
    source = next(
        (
            item for item in Source.query.filter_by(source_type="telegram").all()
            if item.config.get("channel_id") == channel_id
        ),
        None,
    )
    if source is None:
        source = Source(
            name=source_data.get("channel_title") or channel_id or "Telegram channel",
            source_type="telegram",
        )
        db.session.add(source)
    source.config = {
        **source.config,
        "channel_id": channel_id,
        "channel_username": source_data.get("channel_username", ""),
        "sync_frequency": settings.get("sync_frequency", "manual"),
    }
    source.last_fetched_at = datetime.utcnow()
    source.health_status = "ok"
    return source


def _serialize_opportunity(opportunity: Opportunity) -> dict:
    return {
        "id": opportunity.id,
        "title": opportunity.title,
        "organization": opportunity.organization,
        "category": opportunity.opportunity_type,
        "deadline": opportunity.deadline.isoformat() if opportunity.deadline else None,
        "funding_amount": opportunity.extra_fields.get("funding_amount"),
        "eligibility": opportunity.eligibility_text,
        "apply_links": [opportunity.application_url] if opportunity.application_url else [],
        "score": opportunity.opportunity_score,
        "raw_item_id": opportunity.raw_item_id,
    }


@bp.route("/v1/ingest/telegram", methods=["POST", "OPTIONS"])
def ingest_telegram():
    """Accept batches extracted by the local Telegram Web client."""
    if request.method == "OPTIONS":
        return ("", 204)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "JSON object required"}), 400

    source_data = payload.get("source")
    messages = payload.get("messages")
    settings = payload.get("settings") or {}
    if not isinstance(source_data, dict) or not isinstance(messages, list):
        return jsonify({"error": "source and messages are required"}), 400
    if not source_data.get("channel_id"):
        return jsonify({"error": "source.channel_id is required"}), 400

    source = _get_or_create_telegram_source(source_data, settings)
    db.session.flush()
    created = []
    duplicates = 0
    for message in messages[:500]:
        if not isinstance(message, dict) or message.get("message_id") is None:
            continue
        external_id = str(message["message_id"])
        existing = RawItem.query.filter_by(
            source_id=source.id,
            external_id=external_id,
        ).first()
        if existing:
            duplicates += 1
            continue
        raw = RawItem(
            source_id=source.id,
            external_id=external_id,
            raw_content=str(message.get("text") or ""),
            fetched_at=_parse_datetime(message.get("date")),
        )
        raw.extra_metadata = {
            "message_id": message["message_id"],
            "links": message.get("links") or [],
            "has_media": bool(message.get("has_media")),
            "media_type": message.get("media_type", "none"),
            "channel_title": source_data.get("channel_title", ""),
            "channel_username": source_data.get("channel_username", ""),
        }
        db.session.add(raw)
        created.append(raw)
    db.session.commit()

    enriched = 0
    if created:
        from ..services.enrichment_service import EnrichmentService
        service = EnrichmentService()
        for raw in created:
            if service.enrich_one(raw):
                enriched += 1

    return jsonify({
        "status": "ok",
        "source_id": source.id,
        "received": len(messages),
        "created": len(created),
        "duplicates": duplicates,
        "enriched": enriched,
        "pending": len(created) - enriched,
    }), 201


@bp.route("/v1/pipeline/process", methods=["POST"])
def process_pipeline():
    """Process pending raw items through the enrichment pipeline."""
    from ..services.enrichment_service import EnrichmentService
    payload = request.get_json(silent=True) or {}
    count = EnrichmentService().process_pending(payload.get("batch_size"))
    return jsonify({"status": "ok", "processed": count})


@bp.route("/v1/opportunities")
def opportunities(forced_category=None):
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = min(max(request.args.get("per_page", 20, type=int), 1), 100)
    query = Opportunity.query.filter_by(is_active=True, is_duplicate=False)
    category = forced_category or request.args.get("category")
    if category:
        query = query.filter_by(opportunity_type=category)
    result = query.order_by(Opportunity.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return jsonify({
        "items": [_serialize_opportunity(item) for item in result.items],
        "page": result.page,
        "per_page": result.per_page,
        "total": result.total,
        "pages": result.pages,
    })


@bp.route("/v1/scholarships")
def scholarships_api():
    return opportunities("scholarship")


@bp.route("/stats")
def stats():
    """Overview statistics for the dashboard."""
    total = db.session.query(func.count(Opportunity.id)).scalar() or 0
    active = (
        db.session.query(func.count(Opportunity.id))
        .filter(Opportunity.is_active == True, Opportunity.is_duplicate == False)
        .scalar() or 0
    )
    pending = (
        db.session.query(func.count(RawItem.id))
        .filter(RawItem.processing_status == "pending")
        .scalar() or 0
    )
    applications = db.session.query(func.count(Application.id)).scalar() or 0

    return jsonify({
        "total_opportunities": total,
        "active_opportunities": active,
        "pending_items": pending,
        "total_applications": applications,
    })


@bp.route("/opportunities/by-type")
def by_type():
    """Opportunity count grouped by type — for pie/bar charts."""
    rows = (
        db.session.query(Opportunity.opportunity_type, func.count(Opportunity.id))
        .filter(Opportunity.is_active == True, Opportunity.is_duplicate == False)
        .group_by(Opportunity.opportunity_type)
        .order_by(func.count(Opportunity.id).desc())
        .all()
    )
    return jsonify([
        {
            "type":  r[0],
            "label": OpportunityType.LABELS.get(r[0], r[0].title()),
            "count": r[1],
            "color": OpportunityType.COLORS.get(r[0], "secondary"),
            "icon":  OpportunityType.ICONS.get(r[0], "bi-question-circle"),
        }
        for r in rows
    ])


@bp.route("/opportunities/by-country")
def by_country():
    """Opportunity count grouped by country — for pie/bar charts."""
    rows = (
        db.session.query(Opportunity.country, func.count(Opportunity.id))
        .filter(Opportunity.country.isnot(None), Opportunity.is_active == True)
        .group_by(Opportunity.country)
        .order_by(func.count(Opportunity.id).desc())
        .limit(10)
        .all()
    )
    return jsonify([{"country": r[0], "count": r[1]} for r in rows])


# Backward-compat alias — dashboard chart JS still works
@bp.route("/scholarships/by-country")
def scholarships_by_country():
    return by_country()


@bp.route("/scholarships/by-degree")
def by_degree():
    """Preserved for backward compatibility — now returns empty."""
    return jsonify([])


@bp.route("/sources/health")
def sources_health():
    """Health status of all registered sources."""
    sources = Source.query.all()
    return jsonify([
        {
            "id":             s.id,
            "name":           s.name,
            "type":           s.source_type,
            "is_active":      s.is_active,
            "health_status":  s.health_status,
            "last_fetched_at": s.last_fetched_at.isoformat() if s.last_fetched_at else None,
        }
        for s in sources
    ])


@bp.route("/healthz")
def health():
    return jsonify({"status": "ok", "service": "gideon"})
