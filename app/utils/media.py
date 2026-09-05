"""
Media download and path management utilities.

Phase 2 implementation — stubs for the download logic.
"""

import hashlib
import logging
from pathlib import Path
from flask import current_app

log = logging.getLogger("scholarmind.app")


def get_media_dir(file_type: str) -> Path:
    """Return the storage subdirectory for a given file type."""
    storage = current_app.config["STORAGE_DIR"]
    type_map = {
        "pdf": "pdfs",
        "image": "images",
        "document": "documents",
        "video": "documents",
    }
    subdir = type_map.get(file_type, "documents")
    path = storage / subdir
    path.mkdir(parents=True, exist_ok=True)
    return path


def filename_from_url(url: str, file_type: str = "document") -> str:
    """Generate a safe local filename from a URL."""
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    ext_map = {"pdf": ".pdf", "image": ".jpg", "document": ".bin", "video": ".mp4"}
    return f"{url_hash}{ext_map.get(file_type, '.bin')}"
