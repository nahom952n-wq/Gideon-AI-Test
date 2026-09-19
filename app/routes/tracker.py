"""Application tracker routes."""

import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..models import Application, ApplicationStatus, StatusHistory, Scholarship
from ..extensions import db
from .auth import login_required, current_user

bp = Blueprint("tracker", __name__, url_prefix="/tracker")
log = logging.getLogger("scholarmind.app")


@bp.route("/")
@login_required
def index():
    status_filter = request.args.get("status", "")
    query = Application.query.filter_by(user_id=current_user().id).outerjoin(Scholarship)
    if status_filter:
        query = query.filter(Application.status == status_filter)
    applications = query.order_by(Application.updated_at.desc()).all()
    return render_template(
        "tracker/index.html",
        applications=applications,
        statuses=ApplicationStatus.ALL,
        status_filter=status_filter,
    )


@bp.route("/add/<int:scholarship_id>", methods=["POST"])
@login_required
def add(scholarship_id: int):
    scholarship = Scholarship.query.get_or_404(scholarship_id)
    existing = Application.query.filter_by(scholarship_id=scholarship_id, user_id=current_user().id).first()
    if existing:
        flash("Already tracking this scholarship.", "info")
        return redirect(url_for("tracker.index"))

    app = Application(scholarship_id=scholarship_id, user_id=current_user().id, status=ApplicationStatus.INTERESTED)
    db.session.add(app)
    db.session.flush()

    history = StatusHistory(
        application_id=app.id,
        old_status=None,
        new_status=ApplicationStatus.INTERESTED,
        note="Added to tracker",
    )
    db.session.add(history)
    db.session.commit()

    flash(f"'{scholarship.name}' added to tracker.", "success")
    return redirect(url_for("tracker.index"))


@bp.route("/<int:app_id>/update", methods=["POST"])
@login_required
def update(app_id: int):
    application = Application.query.filter_by(id=app_id, user_id=current_user().id).first_or_404()
    new_status = request.form.get("status", "").strip()
    notes = request.form.get("notes", "").strip()

    if new_status and new_status != application.status:
        history = StatusHistory(
            application_id=app_id,
            old_status=application.status,
            new_status=new_status,
        )
        db.session.add(history)
        application.status = new_status
        log.info("Application %d status: %s → %s", app_id, history.old_status, new_status)

    if notes:
        application.notes = notes

    db.session.commit()
    flash("Application updated.", "success")
    return redirect(url_for("tracker.index"))
