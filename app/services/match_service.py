"""
Match service — scores scholarships against the user profile.

The scoring algorithm is transparent: every delta is explained in plain language
and stored in score_breakdown so the user understands exactly why a scholarship
received its score. Scores are cached in MatchScore and invalidated when the
profile hash changes.
"""

import logging
from datetime import datetime
from flask import current_app
from ..extensions import db
from ..models import Scholarship, UserProfile, MatchScore

log = logging.getLogger("scholarmind.app")


class MatchService:
    """Computes and caches match scores for all scholarships."""

    def score_scholarship(
        self, scholarship: Scholarship, profile: UserProfile
    ) -> tuple[int, list[dict]]:
        """
        Compute a compatibility score (0–100) with breakdown.

        Returns:
            (score, breakdown_list) where each breakdown item is:
            {"reason": str, "delta": int, "positive": bool}
        """
        score = 50
        breakdown = []

        def add(reason: str, delta: int) -> None:
            nonlocal score
            score += delta
            breakdown.append({"reason": reason, "delta": abs(delta), "positive": delta > 0})

        if profile.target_countries and scholarship.country:
            if any(
                c.lower() in scholarship.country.lower()
                for c in profile.target_countries
            ):
                add("Country matches your preferences", +20)
            else:
                add("Country not in your preferences", -10)

        if profile.target_degree_levels and scholarship.degree_level:
            if scholarship.degree_level.lower() in [
                d.lower() for d in profile.target_degree_levels
            ]:
                add("Degree level matches your preferences", +15)
            else:
                add("Degree level not in your preferences", -10)

        if profile.funding_preferences and scholarship.funding_type:
            if scholarship.funding_type.lower() in [
                f.lower() for f in profile.funding_preferences
            ]:
                add("Funding type matches your preferences", +10)

        if profile.target_majors and scholarship.fields_of_study_json:
            fields_lower = scholarship.fields_of_study_json.lower()
            if any(m.lower() in fields_lower for m in profile.target_majors):
                add("Field of study matches your major", +15)

        if scholarship.deadline:
            days = (scholarship.deadline - datetime.utcnow().date()).days
            if days < 0:
                add("Deadline has passed", -30)
            elif days <= 30:
                add("Deadline within 30 days — act fast", +5)
            elif days <= 90:
                add("Deadline within 90 days", +10)
            else:
                add("Deadline is far out — more preparation time", +5)

        if profile.gpa and scholarship.min_gpa:
            if profile.gpa >= scholarship.min_gpa:
                add("Your GPA meets the minimum requirement", +10)
            else:
                add("Your GPA is below the minimum requirement", -20)

        if profile.ielts_score and scholarship.ielts_score:
            if profile.ielts_score >= scholarship.ielts_score:
                add("Your IELTS score meets the requirement", +5)
            else:
                add("Your IELTS score is below the requirement", -15)

        if scholarship.ai_confidence:
            if scholarship.ai_confidence >= 0.8:
                add("High AI extraction confidence", +5)
            elif scholarship.ai_confidence < 0.4:
                add("Low AI confidence — verify manually", -5)

        score = max(0, min(100, score))
        return score, breakdown

    def compute_all(self) -> int:
        """Recompute match scores for all scholarships. Returns count updated."""
        profile = UserProfile.query.get(1)
        if not profile:
            return 0

        profile_version = profile.compute_hash()
        scholarships = Scholarship.query.filter_by(is_active=True, is_duplicate=False).all()

        count = 0
        for s in scholarships:
            existing = MatchScore.query.filter_by(
                scholarship_id=s.id, profile_version=profile_version
            ).first()
            if existing:
                continue

            score, breakdown = self.score_scholarship(s, profile)

            ms = MatchScore(
                scholarship_id=s.id,
                profile_version=profile_version,
                score=score,
            )
            ms.score_breakdown = breakdown
            db.session.add(ms)
            count += 1

        db.session.commit()
        log.info("Match scores computed for %d scholarships (profile=%s)", count, profile_version)
        return count
