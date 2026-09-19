"""
Application and StatusHistory models — track the user's scholarship applications.

The status follows a one-way state machine. Every transition is logged in
StatusHistory so the user can see their full journey for each application.
"""

from datetime import datetime
from ..extensions import db


class ApplicationStatus:
    INTERESTED = "interested"
    BOOKMARKED = "bookmarked"
    APPLYING = "applying"
    SUBMITTED = "submitted"
    INTERVIEW = "interview"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    COMPLETED = "completed"

    ALL = [
        INTERESTED,
        BOOKMARKED,
        APPLYING,
        SUBMITTED,
        INTERVIEW,
        ACCEPTED,
        REJECTED,
        COMPLETED,
    ]

    DISPLAY = {
        INTERESTED: ("Interested", "secondary"),
        BOOKMARKED: ("Bookmarked", "info"),
        APPLYING: ("Applying", "primary"),
        SUBMITTED: ("Submitted", "warning"),
        INTERVIEW: ("Interview", "purple"),
        ACCEPTED: ("Accepted", "success"),
        REJECTED: ("Rejected", "danger"),
        COMPLETED: ("Completed", "dark"),
    }


class Application(db.Model):
    """Tracks the user's application status for one scholarship."""

    __tablename__ = "applications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    scholarship_id = db.Column(
        db.Integer, db.ForeignKey("scholarships.id"), nullable=True, unique=True
    )
    opportunity_id = db.Column(
        db.Integer, db.ForeignKey("opportunities.id"), nullable=True, unique=True
    )
    status = db.Column(
        db.String(20),
        default=ApplicationStatus.INTERESTED,
        nullable=False,
        index=True,
    )
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    scholarship = db.relationship("Scholarship", back_populates="applications")
    opportunity = db.relationship("Opportunity", back_populates="applications")
    history = db.relationship(
        "StatusHistory", back_populates="application", lazy="dynamic",
        order_by="StatusHistory.changed_at"
    )

    @property
    def status_display(self) -> tuple[str, str]:
        return ApplicationStatus.DISPLAY.get(self.status, (self.status, "secondary"))

    def __repr__(self) -> str:
        return f"<Application id={self.id} scholarship_id={self.scholarship_id} status={self.status}>"


class StatusHistory(db.Model):
    """Records every status transition for an application."""

    __tablename__ = "status_history"

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(
        db.Integer, db.ForeignKey("applications.id"), nullable=False
    )
    old_status = db.Column(db.String(20), nullable=True)
    new_status = db.Column(db.String(20), nullable=False)
    changed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    note = db.Column(db.Text, nullable=True)

    application = db.relationship("Application", back_populates="history")

    def __repr__(self) -> str:
        return f"<StatusHistory {self.old_status} → {self.new_status} at {self.changed_at}>"
