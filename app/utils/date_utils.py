"""Date and deadline parsing utilities."""

from datetime import date, datetime


def days_until(target: date | None) -> int | None:
    if not target:
        return None
    return (target - datetime.utcnow().date()).days


def deadline_label(target: date | None) -> str:
    days = days_until(target)
    if days is None:
        return "Unknown deadline"
    if days < 0:
        return f"Expired {abs(days)} days ago"
    if days == 0:
        return "Due today"
    if days == 1:
        return "Due tomorrow"
    if days <= 7:
        return f"Due in {days} days"
    if days <= 30:
        return f"Due in {days} days"
    return target.strftime("%d %b %Y")


def deadline_class(target: date | None) -> str:
    """Bootstrap text class for urgency colouring."""
    days = days_until(target)
    if days is None:
        return "text-muted"
    if days < 0:
        return "text-secondary"
    if days <= 7:
        return "text-danger fw-bold"
    if days <= 30:
        return "text-warning"
    return "text-success"
