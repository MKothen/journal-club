from datetime import date, datetime

from sync.announce import due, mark_sending, mark_sent, claim_announcements, superseded
from sync.config import AMSTERDAM
from sync.model import Session, Slot
from tests.test_config import settings

SESSION = Session(day=date(2026, 10, 7), kind="regular", status="scheduled")
SLOT = Slot(page_id="2026-10-07", day=date(2026, 10, 7), presenter="Ann", fmt="help",
            doi="10.1000/xyz", paper_title="A paper", paper_link=None,
            claimed_at=datetime(2026, 9, 20, 9, 0, tzinfo=AMSTERDAM))


def at(day, hour):
    return datetime(2026, 10, day, hour, 0, tzinfo=AMSTERDAM)


def test_friday_announces_an_open_paper_chat_when_nobody_claimed():
    found = due(at(2, 9), [SESSION], [], {}, settings())
    assert [a.kind for a in found] == ["friday"]
    assert "open paper chat" in found[0].text


def test_friday_is_silent_when_the_session_is_claimed():
    assert due(at(2, 9), [SESSION], [SLOT], {}, settings()) == []


def test_monday_names_the_presenter_and_the_paper():
    found = due(at(5, 9), [SESSION], [SLOT], {}, settings())
    assert found[0].kind == "monday"
    assert "Ann" in found[0].text and "A paper" in found[0].text


def test_only_the_newest_overdue_message_is_posted_after_an_outage():
    found = due(at(7, 9), [SESSION], [SLOT], {}, settings())
    assert [a.kind for a in found] == ["wednesday"]


def test_nothing_is_announced_once_the_session_has_started():
    assert due(at(7, 12), [SESSION], [SLOT], {}, settings()) == []


def test_a_sent_announcement_is_never_repeated():
    log = {}
    first = due(at(5, 9), [SESSION], [SLOT], log, settings())[0]
    mark_sending(log, first)
    mark_sent(log, first)
    assert due(at(5, 10), [SESSION], [SLOT], log, settings()) == []


def test_an_entry_stuck_at_sending_is_never_posted_again():
    log = {}
    first = due(at(5, 9), [SESSION], [SLOT], log, settings())[0]
    mark_sending(log, first)
    assert due(at(5, 10), [SESSION], [SLOT], log, settings()) == []


def test_a_cancelled_session_is_not_announced():
    cancelled = Session(day=date(2026, 10, 7), kind="regular", status="cancelled")
    assert due(at(5, 9), [cancelled], [], {}, settings()) == []


def test_a_new_claim_is_confirmed_once():
    log = {}
    found = claim_announcements(at(5, 9), [SLOT], log, settings())
    assert found[0].key == "2026-10-07:claim"
    assert "Ann" in found[0].text
    mark_sending(log, found[0])
    mark_sent(log, found[0])
    assert claim_announcements(at(5, 10), [SLOT], log, settings()) == []


def test_claim_is_not_announced_if_session_already_started():
    assert claim_announcements(at(7, 12), [SLOT], {}, settings()) == []


def test_newest_only_holds_on_second_run():
    """Verify that the latest window is announced, and older windows are never reposted."""
    log = {}
    # First run at Wednesday 09:00 with empty log
    found = due(at(7, 9), [SESSION], [SLOT], log, settings())
    assert [a.kind for a in found] == ["wednesday"]

    # Log the wednesday announcement
    mark_sending(log, found[0])
    mark_sent(log, found[0])

    # Second run at the same time should return nothing
    found = due(at(7, 9), [SESSION], [SLOT], log, settings())
    assert found == []


def test_unclaimed_session_never_reposts_superseded_windows():
    """Friday missed, Monday sent. Later run should not post Friday."""
    log = {}
    # Run on Monday 09:00, all windows have opened but Monday is latest
    found = due(at(5, 9), [SESSION], [], log, settings())
    assert [a.kind for a in found] == ["monday"]

    # Log Monday
    mark_sending(log, found[0])
    mark_sent(log, found[0])

    # Later run on Wednesday should post Wednesday, never Friday
    found = due(at(7, 9), [SESSION], [], log, settings())
    assert [a.kind for a in found] == ["wednesday"]
    assert "friday" not in [a.kind for a in found]


def test_monday_text_does_not_say_tomorrow():
    """Monday message should say 'This Wednesday', not 'Tomorrow'."""
    found = due(at(5, 9), [SESSION], [SLOT], {}, settings())
    assert found[0].kind == "monday"
    assert "Tomorrow" not in found[0].text
    assert "This Wednesday" in found[0].text


def test_monday_text_has_correct_format():
    """Monday text should have unpadded day number."""
    found = due(at(5, 9), [SESSION], [SLOT], {}, settings())
    assert found[0].kind == "monday"
    # Day 7 should appear as "7 October", not "07 October"
    assert "7 October" in found[0].text


def test_superseded_returns_opened_windows_not_latest():
    """Superseded should return keys of windows that have opened but are not the latest and not logged."""
    # At Wednesday 09:00, all three windows have opened (with unclaimed session)
    skipped = superseded(at(7, 9), [SESSION], [], {}, settings())
    # Friday and Monday have opened but Wednesday is the latest
    assert "2026-10-07:friday" in skipped
    assert "2026-10-07:monday" in skipped
    assert "2026-10-07:wednesday" not in skipped  # This is the latest


def test_superseded_excludes_logged_windows():
    """Superseded should not return windows already in the log."""
    log = {"2026-10-07:monday": {"state": "sent", "at": "..."}}
    skipped = superseded(at(7, 9), [SESSION], [], log, settings())
    # Monday was already logged, so only Friday should be superseded
    assert "2026-10-07:friday" in skipped
    assert "2026-10-07:monday" not in skipped


def test_superseded_for_unclaimed_session_includes_friday():
    """For unclaimed session, Friday window should be included in superseded."""
    skipped = superseded(at(7, 9), [SESSION], [], {}, settings())
    assert "2026-10-07:friday" in skipped
    assert "2026-10-07:monday" in skipped
