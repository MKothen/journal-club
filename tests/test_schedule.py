from datetime import date
from sync.schedule import generate_sessions
from tests.test_config import settings


def test_sessions_are_every_other_wednesday_from_the_first_session():
    days = [s.day for s in generate_sessions(settings(), set(), {}, {}, date(2026, 9, 1))]
    assert days[:3] == [date(2026, 9, 30), date(2026, 10, 14), date(2026, 10, 28)]


def test_skipped_weeks_are_dropped():
    sessions = generate_sessions(settings(), {date(2026, 10, 14)}, {}, {}, date(2026, 9, 1))
    assert date(2026, 10, 14) not in [s.day for s in sessions]


def test_an_open_session_replaces_the_regular_one():
    open_sessions = {date(2026, 10, 28): {"title": "Guest", "guest": "A. Author", "length_minutes": 90}}
    sessions = generate_sessions(settings(), set(), open_sessions, {}, date(2026, 9, 1))
    found = [s for s in sessions if s.day == date(2026, 10, 28)][0]
    assert found.kind == "open"
    assert found.guest == "A. Author"
    assert found.length_minutes == 90


def test_status_marks_cancelled_and_past_sessions_are_unrecorded():
    status = {date(2026, 9, 30): "cancelled"}
    sessions = generate_sessions(settings(), set(), {}, status, date(2026, 10, 20))
    by_day = {s.day: s.status for s in sessions}
    assert by_day[date(2026, 9, 30)] == "cancelled"
    assert by_day[date(2026, 10, 14)] == "unrecorded"


def test_the_horizon_limits_how_far_ahead_sessions_exist():
    sessions = generate_sessions(settings(horizon_days=30), set(), {}, {}, date(2026, 9, 1))
    assert max(s.day for s in sessions) <= date(2026, 10, 1)
