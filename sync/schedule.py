"""Generate the session list. Held-ness is decided later, in claims/contributions."""

from datetime import date, timedelta

from sync.config import Settings
from sync.model import Session

INTERVAL = timedelta(days=14)   # a regular session every other week


def generate_sessions(
    settings: Settings,
    skipped: set[date],
    open_sessions: dict[date, dict],
    status: dict[date, str],
    today: date,
) -> list[Session]:
    sessions: list[Session] = []
    day = settings.first_session
    last = _horizon(settings, today)
    while day <= last:
        if day not in skipped:
            sessions.append(_session(day, open_sessions, status, today))
        day += INTERVAL
    return sessions


def off_grid(days, settings: Settings, today: date) -> list[date]:
    """The days, sorted, that fall within the schedule's span but on no
    session date. A date in a hand-edited tab that is off the grid has no
    effect, so it is almost certainly a typing mistake."""
    last = _horizon(settings, today)
    return sorted(day for day in days
                  if settings.first_session <= day <= last
                  and (day - settings.first_session) % INTERVAL)


def _horizon(settings: Settings, today: date) -> date:
    return today + timedelta(days=settings.horizon_days)


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
