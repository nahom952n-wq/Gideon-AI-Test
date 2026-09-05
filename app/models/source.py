"""
Source model — represents a configured data source (Telegram channel, RSS feed, etc.).

The source_type field acts as a discriminator for which adapter handles it.
"""

import json
from datetime import datetime
from ..extensions import db


class Source(db.Model):
    """A registered data source that ScholarMind monitors."""

    __tablename__ = "sources"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    source_type = db.Column(
        db.String(50), nullable=False
    )
    config_json = db.Column(db.Text, default="{}")
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_fetched_at = db.Column(db.DateTime, nullable=True)
    health_status = db.Column(
        db.String(50), default="unknown", nullable=False
    )
    health_message = db.Column(db.Text, nullable=True)

    raw_items = db.relationship("RawItem", back_populates="source", lazy="dynamic")

    @property
    def config(self) -> dict:
        """Deserialize config_json to a Python dict."""
        try:
            return json.loads(self.config_json or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}

    @config.setter
    def config(self, value: dict) -> None:
        self.config_json = json.dumps(value)

    def __repr__(self) -> str:
        return f"<Source id={self.id} type={self.source_type} name={self.name!r}>"
