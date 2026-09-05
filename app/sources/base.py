"""
Abstract base class for all data source adapters.

Every source (Telegram, RSS, CSV, web scraper, manual) must implement
this interface. The ingestion service calls fetch() on each active source
and receives a list of RawItemData dicts — it never knows which source type
produced the data.

To add a new source:
  1. Create a new file in this directory (e.g. rss_source.py)
  2. Subclass BaseSource
  3. Implement fetch() and health_check()
  4. Register the class in the SourceRegistry at the bottom of this file.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawItemData:
    """
    Standardised raw item produced by every source adapter.

    The ingestion service uses this to create RawItem database records.
    """

    source_id: int
    external_id: str | None
    raw_content: str
    raw_metadata: dict = field(default_factory=dict)
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    media_urls: list[str] = field(default_factory=list)


class BaseSource(ABC):
    """Abstract data source — must be subclassed for every integration."""

    source_type: str = "base"

    def __init__(self, source_id: int, config: dict) -> None:
        """
        Args:
            source_id: The database ID of the Source record.
            config: Deserialized config dict from Source.config_json.
        """
        self.source_id = source_id
        self.config = config

    @abstractmethod
    def fetch(self) -> list[RawItemData]:
        """
        Pull new items from this source.

        Returns:
            List of RawItemData. Empty list if nothing new.
        """
        ...

    @abstractmethod
    def health_check(self) -> tuple[str, str]:
        """
        Check connectivity and return (status, message).

        Returns:
            Tuple of (status_string, human_readable_message).
            status_string is one of: "ok", "degraded", "error", "unknown"
        """
        ...


class SourceRegistry:
    """Maps source_type strings to their adapter classes."""

    _registry: dict[str, type[BaseSource]] = {}

    @classmethod
    def register(cls, source_type: str, adapter_class: type[BaseSource]) -> None:
        cls._registry[source_type] = adapter_class

    @classmethod
    def get(cls, source_type: str) -> type[BaseSource] | None:
        return cls._registry.get(source_type)

    @classmethod
    def available_types(cls) -> list[str]:
        return list(cls._registry.keys())


from .manual_source import ManualSource

SourceRegistry.register("manual", ManualSource)
