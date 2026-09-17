"""Settings and time handling. All club times are Europe/Amsterdam."""

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
ARCHIVE_DELAY_DAYS = 7
EXPLAINER_MAX_BYTES = 10_000_000


@dataclass(frozen=True)
class Settings:
    club_name: str
    first_session: date
    session_hour: int
    session_minute: int
    room: str
    horizon_days: int
    site_base_url: str
    form_url: str
    entry_action: str
    entry_page: str


def session_start(day: date, settings: Settings) -> datetime:
    """Local start time of the session on `day`."""
    return datetime(
        day.year, day.month, day.day,
        settings.session_hour, settings.session_minute,
        tzinfo=AMSTERDAM,
    )
