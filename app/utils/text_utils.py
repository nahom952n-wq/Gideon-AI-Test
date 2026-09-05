"""Text sanitisation and formatting utilities."""

import re


def truncate(text: str | None, length: int = 200, suffix: str = "…") -> str:
    if not text:
        return ""
    return text if len(text) <= length else text[:length].rstrip() + suffix


def sanitize(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")
