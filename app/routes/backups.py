"""Backup and restore routes."""

import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request
from ..services.backup_service import BackupService
from .auth import admin_required

bp = Blueprint("backups", __name__, url_prefix="/admin/backups")
log = logging.getLogger("scholarmind.app")
backup_service = BackupService()


@bp.route("/")
@admin_required
def index():
    backups = backup_service.list_backups()
    return render_template("admin/backups.html", backups=backups)


@bp.route("/create", methods=["POST"])
@admin_required
def create():
    try:
        path = backup_service.create_backup()
        flash(f"Backup created: {path.name}", "success")
        log.info("Manual backup created: %s", path)
    except Exception as e:
        flash(f"Backup failed: {e}", "danger")
        log.error("Backup failed: %s", e)
    return redirect(url_for("backups.index"))


@bp.route("/restore/<filename>", methods=["POST"])
@admin_required
def restore(filename: str):
    try:
        backup_service.restore_backup(filename)
        flash(f"Database restored from {filename}.", "success")
        log.info("Database restored from backup: %s", filename)
    except Exception as e:
        flash(f"Restore failed: {e}", "danger")
        log.error("Restore failed: %s", e)
    return redirect(url_for("backups.index"))
