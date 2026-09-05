"""News outlet workspace."""

from flask import Blueprint, render_template

from ..models import Source

bp = Blueprint("news", __name__, url_prefix="/news")


@bp.route("/")
def index():
    sources = [
        source for source in Source.query.filter_by(is_active=True).all()
        if source.config.get("category") == "news"
        or source.source_type in ("news", "telegram_news", "rss_news")
    ]
    return render_template("news/index.html", sources=sources)
