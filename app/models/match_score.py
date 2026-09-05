"""
MatchScore model — cached compatibility scores between a scholarship and the user profile.

Scores are invalidated (profile_version mismatch) when the profile changes,
triggering background recomputation via the scheduler.
"""

import json
from datetime import datetime
from ..extensions import db


class MatchScore(db.Model):
    """Cached score + breakdown for one scholarship against one profile version."""

    __tablename__ = "match_scores"

    id = db.Column(db.Integer, primary_key=True)
    scholarship_id = db.Column(
        db.Integer, db.ForeignKey("scholarships.id"), nullable=False
    )
    profile_version = db.Column(db.String(16), nullable=False)
    score = db.Column(db.Integer, nullable=False, default=0)
    score_breakdown_json = db.Column(db.Text, default="[]")
    computed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    scholarship = db.relationship("Scholarship", back_populates="match_scores")

    __table_args__ = (
        db.UniqueConstraint(
            "scholarship_id", "profile_version", name="uq_score_scholarship_profile"
        ),
    )

    @property
    def score_breakdown(self) -> list:
        """
        List of dicts: [{"reason": "Country match", "delta": 20, "positive": True}, ...]
        """
        try:
            return json.loads(self.score_breakdown_json or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    @score_breakdown.setter
    def score_breakdown(self, value: list) -> None:
        self.score_breakdown_json = json.dumps(value)

    def __repr__(self) -> str:
        return f"<MatchScore scholarship_id={self.scholarship_id} score={self.score}>"
