"""
Backup service — SQLite backup and restore.

Creates timestamped copies of the database in backups/.
Restore replaces the live database file and requires an app restart.
"""

import shutil
import logging
from datetime import datetime
from pathlib import Path
from flask import current_app

log = logging.getLogger("scholarmind.app")


class BackupService:
    """Manages SQLite database backups and restores."""

    def _db_path(self) -> Path:
        uri: str = current_app.config["SQLALCHEMY_DATABASE_URI"]
        return Path(uri.replace("sqlite:///", ""))

    def _backups_dir(self) -> Path:
        return current_app.config["BACKUPS_DIR"]

    def create_backup(self) -> Path:
        """
        Copy the live database to backups/ with a timestamp filename.

        Returns:
            Path to the created backup file.

        Raises:
            FileNotFoundError: If the database file does not exist yet.
        """
        db_path = self._db_path()
        if not db_path.exists():
            raise FileNotFoundError(f"Database not found at {db_path}")

        backups_dir = self._backups_dir()
        backups_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        dest = backups_dir / f"scholarmind_{timestamp}.db"
        shutil.copy2(db_path, dest)

        log.info("Backup created: %s (%.1f KB)", dest, dest.stat().st_size / 1024)
        return dest

    def list_backups(self) -> list[dict]:
        """Return sorted list of backup file metadata (newest first)."""
        backups_dir = self._backups_dir()
        if not backups_dir.exists():
            return []

        files = sorted(backups_dir.glob("*.db"), reverse=True)
        return [
            {
                "filename": f.name,
                "size_kb": round(f.stat().st_size / 1024, 1),
                "created_at": datetime.fromtimestamp(f.stat().st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            }
            for f in files
        ]

    def restore_backup(self, filename: str) -> None:
        """
        Replace the live database with a backup file.

        Warning: This overwrites the current database. An app restart
        may be required for SQLAlchemy to pick up the restored file.

        Args:
            filename: Just the filename (not a full path), e.g.
                      'scholarmind_20240101_120000.db'
        """
        backups_dir = self._backups_dir()
        backup_path = backups_dir / filename

        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {filename}")

        db_path = self._db_path()
        safety_copy = db_path.with_suffix(".pre_restore.db")
        if db_path.exists():
            shutil.copy2(db_path, safety_copy)
            log.info("Safety copy created at %s before restore", safety_copy)

        shutil.copy2(backup_path, db_path)
        log.info("Database restored from backup: %s", filename)
