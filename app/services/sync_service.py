"""
Sync service — orchestrates periodic fetching from all active sources.

Called by APScheduler jobs. Each active Source gets its adapter
instantiated, fetch() called, and results fed into IngestionService.
Also records last_fetched_at and health_status back to the DB.
"""

import logging
from datetime import datetime

from ..extensions import db
from ..models import Source
from ..sources.base import SourceRegistry
from .ingestion_service import IngestionService

log = logging.getLogger("scholarmind.app")
ingestion = IngestionService()


def sync_all_sources(app) -> dict:
    """
    Fetch new items from every active source.

    Args:
        app: Flask app instance (needed to push an app context for DB access).

    Returns:
        Summary dict: {source_id: {"fetched": int, "ingested": int, "error": str|None}}
    """
    summary = {}
    with app.app_context():
        sources = Source.query.filter_by(is_active=True).all()
        for source in sources:
            summary[source.id] = _sync_one(source)
        db.session.commit()
    return summary


def sync_source(source_id: int, app) -> dict:
    """Sync a single source by ID (used by the manual sync route)."""
    with app.app_context():
        source = Source.query.get(source_id)
        if not source:
            return {"error": "Source not found"}
        result = _sync_one(source)
        db.session.commit()
        return result


def _sync_one(source: Source) -> dict:
    """Inner: run fetch + ingest for one Source. DB session must already be open."""
    if source.source_type == "telegram":
        source.health_status = "ok"
        source.health_message = "Fed by the local Telegram Web client"
        return {
            "fetched": 0,
            "ingested": 0,
            "error": None,
            "message": source.health_message,
        }

    adapter_class = SourceRegistry.get(source.source_type)
    if adapter_class is None:
        log.warning("No adapter registered for source_type=%r (id=%d)", source.source_type, source.id)
        source.health_status = "error"
        source.health_message = f"Unknown source type: {source.source_type}"
        return {"fetched": 0, "ingested": 0, "error": source.health_message}

    adapter = adapter_class(source_id=source.id, config=source.config)

    try:
        status, message = adapter.health_check()
        source.health_status = status
        source.health_message = message

        if status == "error":
            log.warning("Source id=%d health_check=error: %s", source.id, message)
            return {"fetched": 0, "ingested": 0, "error": message}

        items = adapter.fetch()
        source.last_fetched_at = datetime.utcnow()

        ingested = ingestion.ingest_batch(items)
        log.info(
            "Synced source id=%d: fetched=%d ingested=%d",
            source.id,
            len(items),
            len(ingested),
        )
        return {"fetched": len(items), "ingested": len(ingested), "error": None}

    except Exception as exc:
        log.exception("Error syncing source id=%d: %s", source.id, exc)
        source.health_status = "error"
        source.health_message = str(exc)[:500]
        return {"fetched": 0, "ingested": 0, "error": str(exc)}
