"""User profile routes."""

import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..models import UserProfile
from .auth import login_required, current_user
from ..extensions import db

bp = Blueprint("profile", __name__, url_prefix="/profile")
log = logging.getLogger("scholarmind.app")


def _get_or_create_profile() -> UserProfile:
    user = current_user()
    profile = UserProfile.query.filter_by(user_id=user.id).first()
    if not profile:
        # Profiles are strictly user-owned. Legacy anonymous rows are left
        # untouched rather than being reassigned to whichever user logs in.
        profile = UserProfile(id=None, user_id=user.id)
        db.session.add(profile)
        db.session.commit()
    return profile


@bp.route("/")
@login_required
def edit():
    profile = _get_or_create_profile()
    return render_template("profile/edit.html", profile=profile)


@bp.route("/save", methods=["POST"])
@login_required
def save():
    profile = _get_or_create_profile()

    profile.name = request.form.get("name", "").strip() or None
    profile.email = request.form.get("email", "").strip() or None

    try:
        profile.age = int(request.form.get("age", "")) or None
    except ValueError:
        profile.age = None

    try:
        profile.gpa = float(request.form.get("gpa", "")) or None
    except ValueError:
        profile.gpa = None

    try:
        profile.ielts_score = float(request.form.get("ielts_score", "")) or None
    except ValueError:
        profile.ielts_score = None

    try:
        profile.toefl_score = int(request.form.get("toefl_score", "")) or None
    except ValueError:
        profile.toefl_score = None

    def _list_from_form(key: str) -> list:
        raw = request.form.get(key, "")
        return [v.strip() for v in raw.split(",") if v.strip()]

    profile.target_countries = _list_from_form("target_countries")
    profile.target_majors = _list_from_form("target_majors")
    profile.target_degree_levels = request.form.getlist("target_degree_levels")
    profile.funding_preferences = request.form.getlist("funding_preferences")
    profile.target_universities = _list_from_form("target_universities")
    profile.languages = _list_from_form("languages")
    profile.career_interests = _list_from_form("career_interests")

    profile.update_hash()
    db.session.commit()

    flash("Profile saved. Match scores will be recomputed in the background.", "success")
    log.info("User profile updated, new hash=%s", profile.profile_hash)
    return redirect(url_for("profile.edit"))
