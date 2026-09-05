"""
Ingestion service — Source → RawItem pipeline.

Handles duplicate detection at the raw level (content hash), media
queuing, and status tracking. Never calls AI directly — that is the
enrichment service's responsibility.
"""

import hashlib
import logging
from datetime import datetime
from flask import current_app
from ..extensions import db
from ..models import RawItem, Source
from ..sources.base import RawItemData

log = logging.getLogger("scholarmind.app")


class IngestionService:
    """Orchestrates the ingestion of raw items from any source."""

    def ingest(self, item_data: RawItemData) -> RawItem | None:
        """
        Store a single RawItemData into the database.

        Skips if the item was already ingested (idempotent by external_id
        or content hash).

        Returns:
            The created RawItem, or None if it was a duplicate.
        """
        content_hash = self._hash(item_data.raw_content or "")

        if item_data.external_id:
            existing = RawItem.query.filter_by(
                source_id=item_data.source_id,
                external_id=item_data.external_id,
            ).first()
            if existing:
                log.debug(
                    "Skipping duplicate raw item (external_id=%s)", item_data.external_id
                )
                return None

        existing_hash = RawItem.query.filter_by(
            source_id=item_data.source_id,
            content_hash=content_hash,
        ).first()
        if existing_hash:
            log.debug("Skipping duplicate raw item (content_hash=%s)", content_hash)
            return None

        raw = RawItem(
            source_id=item_data.source_id,
            external_id=item_data.external_id,
            raw_content=item_data.raw_content,
            content_hash=content_hash,
            fetched_at=item_data.fetched_at,
            processing_status="pending",
        )
        raw.extra_metadata = item_data.raw_metadata
        db.session.add(raw)
        db.session.commit()

        log.info(
            "Ingested raw item id=%d from source_id=%d",
            raw.id,
            item_data.source_id,
        )
        return raw

    def ingest_batch(self, items: list[RawItemData]) -> list[RawItem]:
        """Ingest multiple items, returning only the ones that were new."""
        results = []
        for item in items:
            raw = self.ingest(item)
            if raw:
                results.append(raw)
        return results

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
