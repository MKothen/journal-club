"""Generate the session list. Held-ness is decided later, in claims/contributions."""

from datetime import date, timedelta

from sync.config import Settings
from sync.model import Session


def generate_sessions(
    settings: Settings,
    skipped: set[date],
    open_sessions: dict[date, dict],
    status: dict[date, str],
    today: date,
) -> list[Session]:
    sessions: list[Session] = []
    day = settings.first_session
    last = today + timedelta(days=settings.horizon_days)
    while day <= last:
        if day not in skipped:
            sessions.append(_session(day, open_sessions, status, today))
        day += timedelta(days=14)
    return sessions


def _session(day: date, open_sessions, status, today: date) -> Session:
    marked = status.get(day)
    if marked in ("cancelled", "held"):
        state = marked
    elif day < today:
        state = "unrecorded"
    else:
        state = "scheduled"
    spec = open_sessions.get(day)
    if spec is None:
        return Session(day=day, kind="regular", status=state)
    return Session(
        day=day,
        kind="open",
        status=state,
        title=spec.get("title"),
        guest=spec.get("guest"),
        length_minutes=int(spec.get("length_minutes", 60)),
    )
