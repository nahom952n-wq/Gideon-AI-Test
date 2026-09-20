"""
UserProfile model — a single-row table holding the user's preferences.

The profile is used by the match engine to score scholarships.
We version the profile with a hash so stale match scores can be detected.
"""

import json
import hashlib
from datetime import datetime
from ..extensions import db


class UserProfile(db.Model):
    """Personal preferences used to rank scholarships for one user."""

    __tablename__ = "user_profile"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, unique=True, index=True)
    name = db.Column(db.String(200), nullable=True)
    email = db.Column(db.String(200), nullable=True)
    age = db.Column(db.Integer, nullable=True)
    gpa = db.Column(db.Float, nullable=True)
    ielts_score = db.Column(db.Float, nullable=True)
    toefl_score = db.Column(db.Integer, nullable=True)

    target_countries_json = db.Column(db.Text, default="[]")
    target_majors_json = db.Column(db.Text, default="[]")
    target_degree_levels_json = db.Column(db.Text, default="[]")
    funding_preferences_json = db.Column(db.Text, default="[]")
    target_universities_json = db.Column(db.Text, default="[]")
    languages_json = db.Column(db.Text, default="[]")
    career_interests_json = db.Column(db.Text, default="[]")

    profile_hash = db.Column(db.String(64), nullable=True)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def _get_json(self, field: str) -> list:
        try:
            return json.loads(getattr(self, field) or "[]")
        except (json.JSONDecodeError, TypeError):
            return []

    def _set_json(self, field: str, value: list) -> None:
        setattr(self, field, json.dumps(value))

    @property
    def target_countries(self) -> list:
        return self._get_json("target_countries_json")

    @target_countries.setter
    def target_countries(self, v: list) -> None:
        self._set_json("target_countries_json", v)

    @property
    def target_majors(self) -> list:
        return self._get_json("target_majors_json")

    @target_majors.setter
    def target_majors(self, v: list) -> None:
        self._set_json("target_majors_json", v)

    @property
    def target_degree_levels(self) -> list:
        return self._get_json("target_degree_levels_json")

    @target_degree_levels.setter
    def target_degree_levels(self, v: list) -> None:
        self._set_json("target_degree_levels_json", v)

    @property
    def funding_preferences(self) -> list:
        return self._get_json("funding_preferences_json")

    @funding_preferences.setter
    def funding_preferences(self, v: list) -> None:
        self._set_json("funding_preferences_json", v)

    @property
    def target_universities(self) -> list:
        return self._get_json("target_universities_json")

    @target_universities.setter
    def target_universities(self, v: list) -> None:
        self._set_json("target_universities_json", v)

    @property
    def languages(self) -> list:
        return self._get_json("languages_json")

    @languages.setter
    def languages(self, v: list) -> None:
        self._set_json("languages_json", v)

    @property
    def career_interests(self) -> list:
        return self._get_json("career_interests_json")

    @career_interests.setter
    def career_interests(self, v: list) -> None:
        self._set_json("career_interests_json", v)

    def compute_hash(self) -> str:
        """Compute a hash of the profile to detect staleness of match scores."""
        data = json.dumps(
            {
                "countries": self.target_countries,
                "majors": self.target_majors,
                "degrees": self.target_degree_levels,
                "funding": self.funding_preferences,
                "universities": self.target_universities,
                "languages": self.languages,
                "gpa": self.gpa,
                "ielts": self.ielts_score,
                "toefl": self.toefl_score,
            },
            sort_keys=True,
        )
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def update_hash(self) -> None:
        self.profile_hash = self.compute_hash()

    def __repr__(self) -> str:
        return f"<UserProfile id={self.id} name={self.name!r}>"
