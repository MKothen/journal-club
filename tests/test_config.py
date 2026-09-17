from datetime import date
from sync.config import AMSTERDAM, Settings, session_start


def settings(**over):
    base = dict(
        club_name="NCL Journal Club",
        first_session=date(2026, 9, 30),
        session_hour=11,
        session_minute=0,
        room="Lab room",
        horizon_days=183,
        site_base_url="https://example.github.io/journal-club",
        form_url="https://docs.google.com/forms/d/e/FORM/viewform",
        entry_action="entry.1",
        entry_page="entry.2",
    )
    base.update(over)
    return Settings(**base)


def test_session_start_is_summer_time_in_september():
    start = session_start(date(2026, 9, 30), settings())
    assert start.tzinfo is AMSTERDAM
    assert start.utcoffset().total_seconds() == 2 * 3600


def test_session_start_is_winter_time_in_december():
    start = session_start(date(2026, 12, 9), settings())
    assert start.utcoffset().total_seconds() == 1 * 3600
