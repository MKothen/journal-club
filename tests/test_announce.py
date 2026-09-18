from datetime import date, datetime

from sync.announce import due, mark_sending, mark_sent, claim_announcements
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
