"""Personalized Tailored Feed routes."""

from flask import Blueprint, render_template

from ..extensions import db
from ..models import Opportunity, UserProfile, Application
from .auth import login_required, current_user

bp = Blueprint("feed", __name__, url_prefix="/feed")


def _profile() -> UserProfile:
    profile = UserProfile.query.filter_by(user_id=current_user().id).first()
    return profile or UserProfile(user_id=current_user().id)


def _contains(values: list, text: str) -> bool:
    text = (text or "").lower()
    return any(str(value).lower() in text for value in values)


def _score(opportunity: Opportunity, profile: UserProfile) -> tuple[int, list[str]]:
    searchable = " ".join(
        [
            opportunity.title or "",
            opportunity.organization or "",
            opportunity.country or "",
            opportunity.summary or "",
            opportunity.keywords_json or "",
            opportunity.tags_json or "",
            opportunity.extra_fields_json or "",
        ]
    )
    reasons = []
    score = opportunity.opportunity_score or 0

    if profile.target_countries and _contains(profile.target_countries, opportunity.country):
        score += 35
        reasons.append("target country")
    if profile.target_degree_levels and _contains(profile.target_degree_levels, searchable):
        score += 25
        reasons.append("degree level")
    if profile.target_majors and _contains(profile.target_majors, searchable):
        score += 25
        reasons.append("major or field")
    if profile.target_universities and _contains(profile.target_universities, searchable):
        score += 10
        reasons.append("preferred institution")
    if profile.funding_preferences and _contains(profile.funding_preferences, searchable):
        score += 10
        reasons.append("funding preference")

    news_terms = (
        "policy", "visa", "immigration", "international student", "law",
        "regulation", "travel", "work permit", "residence", "government",
    )
    if opportunity.opportunity_type == "announcement" or _contains(news_terms, searchable):
        score += 20
        reasons.append("policy and global news")

    return score, reasons


@bp.route("/")
@login_required
def index():
    profile = _profile()
    opportunities = (
        Opportunity.query
        .filter_by(is_active=True, is_duplicate=False)
        .order_by(Opportunity.created_at.desc())
        .all()
    )
    tracked_ids = {
        row[0] for row in db.session.query(Application.opportunity_id)
        .filter(Application.user_id == current_user().id, Application.opportunity_id.isnot(None)).all()
    }
    ranked = []
    news = []
    for opportunity in opportunities:
        if opportunity.id in tracked_ids:
            continue
        score, reasons = _score(opportunity, profile)
        item = {"opportunity": opportunity, "score": score, "reasons": reasons}
        if "policy and global news" in reasons:
            news.append(item)
        else:
            ranked.append(item)

    ranked.sort(key=lambda item: item["score"], reverse=True)
    news.sort(key=lambda item: item["score"], reverse=True)
    return render_template(
        "feed/index.html",
        recommendations=ranked[:30],
        news=news[:15],
        profile=profile,
    )
