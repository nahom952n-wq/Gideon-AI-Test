"""Pluggable source adapter package."""

from .base import BaseSource, RawItemData, SourceRegistry
from .manual_source import ManualSource
from .telegram_source import TelegramSource

SourceRegistry.register("manual", ManualSource)
SourceRegistry.register("telegram", TelegramSource)

__all__ = ["BaseSource", "RawItemData", "SourceRegistry", "ManualSource", "TelegramSource"]
