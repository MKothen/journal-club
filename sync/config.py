"""Settings and time handling. All club times are Europe/Amsterdam."""

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
ARCHIVE_DELAY_DAYS = 7
EXPLAINER_MAX_BYTES = 10_000_000

# A Google Forms prefilled link must carry a multiple-choice option's exact
# visible text, not its code, so the two are defined together here. The
# sheet reader maps a label back to its code; the rest of the system only
# ever sees the code.
ACTION_LABELS = {
    "claim": "Claim a session",
    "takeaway": "Add a takeaway",
    "wishlist": "Suggest a paper",
    "interest": "I'd come to this",
    "page": "Add to a page",
}
FORMAT_LABELS = {
    "help": "Help me read this",
    "full": "Full presentation",
    "short": "Short slot on one figure",
}
PART_LABELS = {
    "synthesis": "Discussion synthesis",
    "connections": "What it means for our work",
    "slides": "Slides link",
    "explainer": "Explainer link",
    "next": "What happened next",
    "reply": "Author reply",
}


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
