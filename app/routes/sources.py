"""Sources routes — manage data sources (Telegram channels, RSS feeds, manual)."""

import logging
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session, jsonify, current_app,
)
from ..models import (
    Source,
    RawItem,
    Opportunity,
    Scholarship,
    MediaAttachment,
    Application,
    StatusHistory,
    MatchScore,
    NotificationLog,
)
from ..extensions import db
from .auth import login_required, current_user

bp = Blueprint("sources", __name__, url_prefix="/sources")
log = logging.getLogger("scholarmind.app")


# ---------------------------------------------------------------------------
# Source list
# ---------------------------------------------------------------------------

@bp.route("/")
@login_required
def manage():
    sources = [
        source for source in Source.query.filter_by(user_id=current_user().id).order_by(Source.created_at.desc()).all()
        if not source.config.get("deleted", False)
    ]
    # Attach raw item counts
    counts = {}
    for s in sources:
        counts[s.id] = RawItem.query.filter_by(source_id=s.id).count()

    from ..services.telegram_service import get_service
    tg_service = get_service(current_user().id)
    tg_connected = tg_service is not None and tg_service.is_connected()
    tg_configured = current_app.config.get("TELEGRAM_API_ID") and current_app.config.get("TELEGRAM_API_HASH")

    return render_template(
        "sources/manage.html",
        sources=sources,
        item_counts=counts,
        tg_connected=tg_connected,
        tg_configured=tg_configured,
        focus=request.args.get("focus", ""),
    )


# ---------------------------------------------------------------------------
# Add source
# ---------------------------------------------------------------------------

@bp.route("/add", methods=["POST"])
@login_required
def add():
    name = request.form.get("name", "").strip()
    source_type = request.form.get("source_type", "").strip()
    config_value = request.form.get("config_value", "").strip()
    limit = request.form.get("limit", "100").strip()
    since_hours = request.form.get("since_hours", "24").strip()
    min_length = request.form.get("min_length", "30").strip()
    category = request.form.get("category", "").strip()

    if not name or not source_type:
        flash("Name and source type are required.", "danger")
        return redirect(url_for("sources.manage"))

    config = {}
    if source_type == "telegram":
        if not config_value:
            flash("Channel username or ID is required for Telegram sources.", "danger")
            return redirect(url_for("sources.manage"))
        config = {
            "channel": config_value,
            "limit": int(limit) if limit.isdigit() else 100,
            "since_hours": int(since_hours) if since_hours.isdigit() else 24,
            "min_length": int(min_length) if min_length.isdigit() else 30,
        }
    elif source_type == "rss":
        config = {"url": request.form.get("rss_url", "").strip() or config_value}
    elif source_type == "manual":
        config = {}
    if category:
        config["category"] = category

    source = Source(name=name, source_type=source_type, user_id=current_user().id)
    source.config = config
    db.session.add(source)
    db.session.commit()

    flash(f"Source '{name}' added successfully.", "success")
    log.info("New source added: type=%s name=%r", source_type, name)
    return redirect(url_for("sources.manage"))


# ---------------------------------------------------------------------------
# Toggle / Delete
# ---------------------------------------------------------------------------

@bp.route("/<int:source_id>/toggle", methods=["POST"])
@login_required
def toggle(source_id: int):
    source = Source.query.filter_by(id=source_id, user_id=current_user().id).first_or_404()
    source.is_active = not source.is_active
    db.session.commit()
    state = "activated" if source.is_active else "paused"
    flash(f"Source '{source.name}' {state}.", "success")
    return redirect(url_for("sources.manage"))


@bp.route("/<int:source_id>/delete", methods=["POST"])
@login_required
def delete(source_id: int):
    source = Source.query.filter_by(id=source_id, user_id=current_user().id).first_or_404()
    name = source.name

    raw_items = RawItem.query.filter_by(source_id=source.id).all()
    raw_item_ids = [item.id for item in raw_items]
    opportunity_ids = [
        row[0] for row in db.session.query(Opportunity.id)
        .filter(Opportunity.raw_item_id.in_(raw_item_ids)).all()
    ] if raw_item_ids else []
    scholarship_ids = [
        row[0] for row in db.session.query(Scholarship.id)
        .filter(Scholarship.raw_item_id.in_(raw_item_ids)).all()
    ] if raw_item_ids else []

    # Remove dependent tracker/history and cached records first.
    application_ids = []
    application_query = Application.query
    if scholarship_ids:
        application_ids.extend(
            row[0] for row in application_query.with_entities(Application.id)
            .filter(Application.scholarship_id.in_(scholarship_ids)).all()
        )
    if opportunity_ids:
        application_ids.extend(
            row[0] for row in application_query.with_entities(Application.id)
            .filter(Application.opportunity_id.in_(opportunity_ids)).all()
        )
    if application_ids:
        StatusHistory.query.filter(StatusHistory.application_id.in_(application_ids)).delete(
            synchronize_session=False
        )
        Application.query.filter(Application.id.in_(application_ids)).delete(
            synchronize_session=False
        )
    if scholarship_ids:
        MatchScore.query.filter(MatchScore.scholarship_id.in_(scholarship_ids)).delete(
            synchronize_session=False
        )
        NotificationLog.query.filter(
            NotificationLog.scholarship_id.in_(scholarship_ids)
        ).delete(synchronize_session=False)
        Scholarship.query.filter(Scholarship.duplicate_of_id.in_(scholarship_ids)).update(
            {Scholarship.duplicate_of_id: None}, synchronize_session=False
        )
        Scholarship.query.filter(Scholarship.id.in_(scholarship_ids)).delete(
            synchronize_session=False
        )
    if opportunity_ids:
        Opportunity.query.filter(Opportunity.duplicate_of_id.in_(opportunity_ids)).update(
            {Opportunity.duplicate_of_id: None}, synchronize_session=False
        )
        Opportunity.query.filter(Opportunity.id.in_(opportunity_ids)).delete(
            synchronize_session=False
        )

    # Delete downloaded attachments and their database rows.
    attachments = (
        MediaAttachment.query.filter(MediaAttachment.raw_item_id.in_(raw_item_ids)).all()
        if raw_item_ids else []
    )
    for attachment in attachments:
        if attachment.stored_path:
            try:
                from pathlib import Path
                Path(attachment.stored_path).unlink(missing_ok=True)
            except OSError:
                log.warning("Could not remove attachment %r", attachment.stored_path)
    if raw_item_ids:
        MediaAttachment.query.filter(
            MediaAttachment.raw_item_id.in_(raw_item_ids)
        ).delete(synchronize_session=False)
        RawItem.query.filter(RawItem.id.in_(raw_item_ids)).delete(
            synchronize_session=False
        )

    db.session.delete(source)
    db.session.commit()
    flash(f"Source '{name}' and all imported content were deleted.", "info")
    log.info("Source and imported content deleted: id=%d name=%r", source_id, name)
    return redirect(url_for("sources.manage"))


# ---------------------------------------------------------------------------
# Manual sync
# ---------------------------------------------------------------------------

@bp.route("/<int:source_id>/sync", methods=["POST"])
@login_required
def sync_one(source_id: int):
    source = Source.query.get_or_404(source_id)
    app = current_app._get_current_object()

    from ..services.sync_service import sync_source
    result = sync_source(source_id=source_id, app=app, user_id=current_user().id)

    if result.get("error"):
        flash(f"Sync failed for '{source.name}': {result['error']}", "danger")
    else:
        flash(
            f"Synced '{source.name}': {result['fetched']} fetched, {result['ingested']} new items ingested.",
            "success",
        )
    return redirect(url_for("sources.manage"))


@bp.route("/sync-all", methods=["POST"])
@login_required
def sync_all():
    app = current_app._get_current_object()
    from ..services.sync_service import sync_all_sources
    summary = sync_all_sources(app=app, user_id=current_user().id)

    total_fetched = sum(v.get("fetched", 0) for v in summary.values())
    total_ingested = sum(v.get("ingested", 0) for v in summary.values())
    errors = [v["error"] for v in summary.values() if v.get("error")]

    if errors:
        flash(f"Sync complete with errors: {'; '.join(errors[:3])}", "warning")
    else:
        flash(f"All sources synced: {total_fetched} fetched, {total_ingested} new items.", "success")
    return redirect(url_for("sources.manage"))


# ---------------------------------------------------------------------------
# Telegram setup — 2-step OTP auth flow
# ---------------------------------------------------------------------------

@bp.route("/telegram/setup", methods=["GET"])
@login_required
def telegram_setup():
    from ..services.telegram_service import get_service
    tg_service = get_service(current_user().id)
    tg_configured = bool(
        current_app.config.get("TELEGRAM_API_ID")
        and current_app.config.get("TELEGRAM_API_HASH")
    )
    tg_connected = tg_service is not None and tg_service.is_connected()
    phone_sent = session.get("tg_phone_sent", False)
    two_factor_required = session.get("tg_2fa_required", False)
    return render_template(
        "sources/telegram_setup.html",
        tg_configured=tg_configured,
        tg_connected=tg_connected,
        phone_sent=phone_sent,
        two_factor_required=two_factor_required,
        password_hint=session.get("tg_password_hint", ""),
        tg_phone=session.get("tg_phone", ""),
    )


@bp.route("/telegram/send-code", methods=["POST"])
@login_required
def telegram_send_code():
    phone = request.form.get("phone", "").strip()
    if not phone:
        flash("Phone number is required.", "danger")
        return redirect(url_for("sources.telegram_setup"))

    from ..services.telegram_service import get_service, reset_service
    reset_service(current_user().id)
    session.pop("tg_2fa_required", None)
    session.pop("tg_password_hint", None)
    service = get_service(current_user().id)
    if not service:
        flash("Telegram API credentials are not configured. Add them in Settings → Telegram Credentials first.", "danger")
        return redirect(url_for("sources.telegram_setup"))

    try:
        phone_code_hash = service.send_code(phone)
        session["tg_phone"] = phone
        session["tg_phone_code_hash"] = phone_code_hash
        session["tg_phone_sent"] = True
        flash(f"Code sent to {phone}. Check your Telegram app.", "success")
    except RuntimeError as exc:
        flash(str(exc), "danger")

    return redirect(url_for("sources.telegram_setup"))


@bp.route("/telegram/verify", methods=["POST"])
@login_required
def telegram_verify():
    code = request.form.get("code", "").strip()
    phone = session.get("tg_phone", "")
    phone_code_hash = session.get("tg_phone_code_hash", "")

    if not code or not phone or not phone_code_hash:
        flash("Session expired. Please start over.", "warning")
        session.pop("tg_phone_sent", None)
        return redirect(url_for("sources.telegram_setup"))

    from ..services.telegram_service import (
        TelegramTwoFactorRequired,
        get_service,
    )
    service = get_service(current_user().id)
    if not service:
        flash("Telegram service unavailable.", "danger")
        return redirect(url_for("sources.telegram_setup"))

    try:
        service.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        session.pop("tg_phone", None)
        session.pop("tg_phone_code_hash", None)
        session.pop("tg_phone_sent", None)
        flash("Telegram connected successfully! You can now add Telegram sources.", "success")
        log.info("Telegram authenticated for phone=%s", phone)
    except TelegramTwoFactorRequired as exc:
        session["tg_2fa_required"] = True
        session["tg_password_hint"] = exc.hint
        flash("Verification code accepted. Enter your Telegram two-step password.", "info")
    except RuntimeError as exc:
        flash(str(exc), "danger")

    return redirect(url_for("sources.telegram_setup"))


@bp.route("/telegram/verify-password", methods=["POST"])
@login_required
def telegram_verify_password():
    password = request.form.get("password", "")
    if not password:
        flash("Telegram password is required.", "danger")
        return redirect(url_for("sources.telegram_setup"))

    if not session.get("tg_2fa_required") or not session.get("tg_phone"):
        flash("Session expired. Please start over.", "warning")
        session.pop("tg_phone_sent", None)
        session.pop("tg_2fa_required", None)
        session.pop("tg_password_hint", None)
        return redirect(url_for("sources.telegram_setup"))

    from ..services.telegram_service import get_service
    service = get_service(current_user().id)
    if not service:
        flash("Telegram service unavailable.", "danger")
        return redirect(url_for("sources.telegram_setup"))

    try:
        service.sign_in_password(password)
        session.pop("tg_phone", None)
        session.pop("tg_phone_code_hash", None)
        session.pop("tg_phone_sent", None)
        session.pop("tg_2fa_required", None)
        session.pop("tg_password_hint", None)
        flash("Telegram connected successfully! You can now add Telegram sources.", "success")
        log.info("Telegram authenticated with two-step verification")
    except RuntimeError as exc:
        flash(str(exc), "danger")

    return redirect(url_for("sources.telegram_setup"))


@bp.route("/telegram/disconnect", methods=["POST"])
@login_required
def telegram_disconnect():
    from ..services.telegram_service import get_service, reset_service
    service = get_service(current_user().id)
    if service:
        service.disconnect()
    reset_service(current_user().id)
    session.pop("tg_phone", None)
    session.pop("tg_phone_code_hash", None)
    session.pop("tg_phone_sent", None)
    session.pop("tg_2fa_required", None)
    session.pop("tg_password_hint", None)
    flash("Telegram session disconnected and removed.", "info")
    log.info("Telegram session disconnected")
    return redirect(url_for("sources.telegram_setup"))


# ---------------------------------------------------------------------------
# Telegram status + dialogs API (AJAX)
# ---------------------------------------------------------------------------

@bp.route("/telegram/status")
@login_required
def telegram_status():
    from ..services.telegram_service import get_service
    service = get_service(current_user().id)
    configured = bool(
        current_app.config.get("TELEGRAM_API_ID")
        and current_app.config.get("TELEGRAM_API_HASH")
    )
    connected = service is not None and service.is_connected()
    return jsonify({"configured": configured, "connected": connected})


@bp.route("/telegram/dialogs")
@login_required
def telegram_dialogs():
    """
    Return all chats the authenticated account can access.

    Includes public channels, private channels (joined), and private groups.
    Used by the sources UI to let the user browse and select chats.
    """
    from ..services.telegram_service import get_service
    service = get_service(current_user().id)
    if not service or not service.is_connected():
        return jsonify({"error": "Not connected", "dialogs": []})
    try:
        query = request.args.get("q", "").strip().lower()
        dialogs = service.list_dialogs(limit=300)
        if query:
            dialogs = [
                dialog for dialog in dialogs
                if query in str(dialog.get("name") or "").lower()
                or query in str(dialog.get("username") or "").lower()
                or query in str(dialog.get("id") or "").lower()
            ]
        # Sort: channels first, then groups, then private — by name
        order = {"channel": 0, "group": 1, "private": 2}
        dialogs.sort(
            key=lambda d: (
                order.get(d.get("type"), 3),
                str(d.get("name") or d.get("username") or d.get("id") or "").lower(),
            )
        )
        return jsonify({"dialogs": dialogs})
    except Exception as exc:
        log.error("telegram_dialogs error: %s", exc)
        return jsonify({"error": str(exc), "dialogs": []})
