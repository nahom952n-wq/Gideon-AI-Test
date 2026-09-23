"""
Opportunities routes — list, detail, search, re-analyze.

Phase 3: queries the Opportunity table (generic, multi-type).
The URL prefix /scholarships/ is preserved for backward compatibility —
links and bookmarks continue to work unchanged.
"""

import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from ..models import (
    Application,
    ApplicationStatus,
    MediaAttachment,
    Scholarship,
    StatusHistory,
)
from ..models.opportunity import Opportunity, OpportunityType
from ..extensions import db
from .auth import login_required, current_user, admin_required

bp = Blueprint("scholarships", __name__, url_prefix="/scholarships")
log = logging.getLogger("scholarmind.app")


@bp.route("/")
def list_view():
    """Browse and filter all opportunities."""
    page     = request.args.get("page", 1, type=int)
    q        = request.args.get("q", "").strip()
    country  = request.args.get("country", "").strip()
    opp_type = request.args.get("type", "").strip()
    sort     = request.args.get("sort", "recent")

    query = Opportunity.query.filter_by(is_active=True, is_duplicate=False)

    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Opportunity.title.ilike(like),
                Opportunity.summary.ilike(like),
                Opportunity.organization.ilike(like),
                Opportunity.keywords_json.ilike(like),
            )
        )

    if country:
        query = query.filter(Opportunity.country.ilike(f"%{country}%"))

    if opp_type and opp_type in OpportunityType.ALL:
        query = query.filter(Opportunity.opportunity_type == opp_type)

    if sort == "score":
        query = query.order_by(Opportunity.opportunity_score.desc())
    elif sort == "deadline":
        query = query.filter(Opportunity.deadline.isnot(None)).order_by(Opportunity.deadline.asc())
    else:
        query = query.order_by(Opportunity.created_at.desc())

    opportunities = query.paginate(page=page, per_page=20, error_out=False)

    # Filter options
    countries = (
        db.session.query(Opportunity.country)
        .filter(Opportunity.country.isnot(None), Opportunity.is_active == True)
        .distinct()
        .order_by(Opportunity.country)
        .all()
    )

    # Type counts for sidebar
    type_counts = {}
    rows = (
        db.session.query(Opportunity.opportunity_type, db.func.count(Opportunity.id))
        .filter(Opportunity.is_active == True, Opportunity.is_duplicate == False)
        .group_by(Opportunity.opportunity_type)
        .all()
    )
    for r in rows:
        type_counts[r[0]] = r[1]

    return render_template(
        "scholarships/list.html",
        opportunities=opportunities,
        countries=[c[0] for c in countries if c[0]],
        type_counts=type_counts,
        opportunity_types=OpportunityType.ALL,
        opportunity_icons=OpportunityType.ICONS,
        opportunity_colors=OpportunityType.COLORS,
        opportunity_labels=OpportunityType.LABELS,
        filters={
            "q": q,
            "country": country,
            "type": opp_type,
            "sort": sort,
        },
    )


@bp.route("/<int:opportunity_id>")
def detail(opportunity_id: int):
    opp = Opportunity.query.get_or_404(opportunity_id)
    raw_item = opp.raw_item
    return render_template(
        "scholarships/detail.html",
        opportunity=opp,
        raw_item=raw_item,
    )


@bp.route("/<int:opportunity_id>/delete", methods=["POST"])
def delete(opportunity_id: int):
    """Permanently remove an opportunity and its generated cache records."""
    opportunity = Opportunity.query.get_or_404(opportunity_id)
    title = opportunity.title or "Untitled opportunity"
    raw_item = opportunity.raw_item

    application_ids = [
        row[0]
        for row in db.session.query(Application.id)
        .filter(Application.opportunity_id == opportunity.id)
        .all()
    ]
    if application_ids:
        StatusHistory.query.filter(
            StatusHistory.application_id.in_(application_ids)
        ).delete(synchronize_session=False)
        Application.query.filter(
            Application.id.in_(application_ids)
        ).delete(synchronize_session=False)

    Opportunity.query.filter(Opportunity.duplicate_of_id == opportunity.id).update(
        {Opportunity.duplicate_of_id: None},
        synchronize_session=False,
    )
    db.session.delete(opportunity)

    if raw_item is not None:
        sibling_opportunity = Opportunity.query.filter(
            Opportunity.raw_item_id == raw_item.id,
            Opportunity.id != opportunity_id,
        ).first()
        sibling_scholarship = Scholarship.query.filter_by(raw_item_id=raw_item.id).first()
        if sibling_opportunity is None and sibling_scholarship is None:
            MediaAttachment.query.filter_by(raw_item_id=raw_item.id).delete(
                synchronize_session=False
            )
            db.session.delete(raw_item)

    db.session.commit()
    flash(f"'{title}' was permanently deleted.", "info")
    log.info("Opportunity deleted: id=%d title=%r", opportunity_id, title)
    return redirect(url_for("scholarships.list_view"))


@bp.route("/<int:opportunity_id>/reanalyze", methods=["POST"])
def reanalyze(opportunity_id: int):
    """Queue an opportunity for re-analysis through the Phase 3 pipeline."""
    opp = Opportunity.query.get_or_404(opportunity_id)
    if opp.raw_item:
        opp.raw_item.processing_status = "pending"
        db.session.commit()
        flash("Opportunity queued for re-analysis.", "success")
        log.info("Re-analysis queued for opportunity_id=%d", opportunity_id)
    else:
        flash("No raw data available for re-analysis.", "warning")
    return redirect(url_for("scholarships.detail", opportunity_id=opportunity_id))


@bp.route("/<int:opportunity_id>/track", methods=["POST"])
@login_required
def track(opportunity_id: int):
    """Move an opportunity into the application tracker."""
    opportunity = Opportunity.query.get_or_404(opportunity_id)
    existing = Application.query.filter_by(opportunity_id=opportunity.id, user_id=current_user().id).first()
    if existing:
        opportunity.is_active = False
        db.session.commit()
        flash("This opportunity is already in your tracker.", "info")
        return redirect(url_for("tracker.index"))

    # Keep compatibility with the legacy non-null scholarship_id column in
    # databases created before generic opportunities were introduced.
    legacy = (
        Scholarship.query.filter_by(raw_item_id=opportunity.raw_item_id).first()
        if opportunity.raw_item_id
        else None
    )
    if not legacy:
        legacy = Scholarship(
            raw_item_id=opportunity.raw_item_id,
            name=opportunity.title,
            university=opportunity.organization,
            country=opportunity.country,
            deadline=opportunity.deadline,
            deadline_raw=opportunity.deadline_raw,
            summary=opportunity.summary,
            application_url=opportunity.application_url,
            official_website=opportunity.official_website,
        )
        db.session.add(legacy)
        db.session.flush()

    application = Application.query.filter_by(
        scholarship_id=legacy.id, user_id=current_user().id
    ).first()
    if application:
        application.opportunity_id = opportunity.id
        application.status = ApplicationStatus.INTERESTED
    else:
        application = Application(
            user_id=current_user().id,
            scholarship_id=legacy.id,
            opportunity_id=opportunity.id,
            status=ApplicationStatus.INTERESTED,
        )
        db.session.add(application)
        db.session.flush()
        db.session.add(StatusHistory(
            application_id=application.id,
            old_status=None,
            new_status=ApplicationStatus.INTERESTED,
            note="Moved from opportunities",
        ))
    opportunity.is_active = False
    db.session.commit()
    flash(f"'{opportunity.title or 'Opportunity'}' moved to your tracker.", "success")
    return redirect(url_for("tracker.index"))


# Backward-compat alias — old links to /scholarships/<id> still work
# (kept as-is; route parameter name changed internally only)
