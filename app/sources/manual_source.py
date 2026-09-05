"""
Manual entry source adapter.

The simplest source — the user types scholarship info directly into a form.
Provides a clean example of how to implement BaseSource.
"""

import logging
from .base import BaseSource, RawItemData

log = logging.getLogger("scholarmind.app")


class ManualSource(BaseSource):
    """Adapter for manually entered scholarship data."""

    source_type = "manual"

    def fetch(self) -> list[RawItemData]:
        """Manual sources do not poll — entries are created directly."""
        return []

    def health_check(self) -> tuple[str, str]:
        return "ok", "Manual source is always available."
