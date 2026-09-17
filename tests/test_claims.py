from datetime import date, datetime

from sync.claims import resolve_claims
from sync.config import AMSTERDAM
from sync.model import Session


def at(day, hour):
    return datetime(2026, 9, day, hour, 0, tzinfo=AMSTERDAM)


def claim(name, day, fmt="full", when=None, hidden=False):
    return {
        "name": name,
        "day": day,
        "fmt": fmt,
        "doi": "10.1000/xyz",
        "paper_title": None,
        "paper_link": None,
        "submitted_at": when or at(1, 9),
        "hidden": hidden,
    }


SESSIONS = [
    Session(day=date(2026, 10, 7), kind="regular", status="scheduled"),
    Session(day=date(2026, 10, 21), kind="open", status="scheduled", guest="A. Author"),
]


def test_a_long_claim_gets_the_bare_date_as_its_page_id():
    result = resolve_claims(SESSIONS, [claim("Max", date(2026, 10, 7))], {})
    assert [s.page_id for s in result.slots] == ["2026-10-07"]


def test_two_short_claims_share_a_session_as_a_and_b():
    rows = [
        claim("Ann", date(2026, 10, 7), "short", at(1, 9)),
        claim("Bo", date(2026, 10, 7), "short", at(2, 9)),
    ]
    result = resolve_claims(SESSIONS, rows, {})
    assert [s.page_id for s in result.slots] == ["2026-10-07-a", "2026-10-07-b"]


def test_the_earliest_claim_wins_and_the_later_one_is_rejected():
    rows = [
        claim("Late", date(2026, 10, 7), "full", at(3, 9)),
        claim("Early", date(2026, 10, 7), "full", at(1, 9)),
    ]
    result = resolve_claims(SESSIONS, rows, {})
    assert [s.presenter for s in result.slots] == ["Early"]
    assert result.rejections[0].name == "Late"
    assert result.rejections[0].reason == "taken"


def test_a_claim_on_an_open_session_is_rejected():
    result = resolve_claims(SESSIONS, [claim("Max", date(2026, 10, 21))], {})
    assert result.slots == []
    assert result.rejections[0].reason == "not-claimable"


def test_a_claim_on_an_unknown_date_is_rejected():
    result = resolve_claims(SESSIONS, [claim("Max", date(2026, 10, 8))], {})
    assert result.rejections[0].reason == "not-claimable"


def test_ids_are_frozen_once_assigned():
    rows = [claim("Ann", date(2026, 10, 7), "short", at(1, 9))]
    first = resolve_claims(SESSIONS, rows, {})
    rows.insert(0, claim("Bo", date(2026, 10, 7), "short", at(2, 9)))
    second = resolve_claims(SESSIONS, rows, first.assigned)
    ids = {s.presenter: s.page_id for s in second.slots}
    assert ids["Ann"] == "2026-10-07-a"
    assert ids["Bo"] == "2026-10-07-b"


def test_a_hidden_claim_retires_its_id_and_the_survivor_keeps_its_own():
    rows = [
        claim("Ann", date(2026, 10, 7), "short", at(1, 9)),
        claim("Bo", date(2026, 10, 7), "short", at(2, 9)),
    ]
    first = resolve_claims(SESSIONS, rows, {})
    rows[0] = claim("Ann", date(2026, 10, 7), "short", at(1, 9), hidden=True)
    second = resolve_claims(SESSIONS, rows, first.assigned)
    assert [s.page_id for s in second.slots] == ["2026-10-07-b"]


def test_a_released_long_claim_frees_capacity_but_not_its_id():
    rows = [claim("Ann", date(2026, 10, 7), "full", at(1, 9))]
    first = resolve_claims(SESSIONS, rows, {})
    assert [s.page_id for s in first.slots] == ["2026-10-07"]

    rows = [
        claim("Ann", date(2026, 10, 7), "full", at(1, 9), hidden=True),
        claim("Carl", date(2026, 10, 7), "full", at(2, 9)),
    ]
    second = resolve_claims(SESSIONS, rows, first.assigned)
    assert [s.presenter for s in second.slots] == ["Carl"]
    assert [s.page_id for s in second.slots] == ["2026-10-07-2"]


def test_a_released_short_claim_frees_capacity_and_gets_the_next_free_id():
    rows = [
        claim("Ann", date(2026, 10, 7), "short", at(1, 9)),
        claim("Bo", date(2026, 10, 7), "short", at(2, 9)),
    ]
    first = resolve_claims(SESSIONS, rows, {})
    assert [s.page_id for s in first.slots] == ["2026-10-07-a", "2026-10-07-b"]

    rows = [
        claim("Ann", date(2026, 10, 7), "short", at(1, 9), hidden=True),
        claim("Bo", date(2026, 10, 7), "short", at(2, 9)),
        claim("Dee", date(2026, 10, 7), "short", at(3, 9)),
    ]
    second = resolve_claims(SESSIONS, rows, first.assigned)
    ids = {s.presenter: s.page_id for s in second.slots}
    assert ids["Bo"] == "2026-10-07-b"
    assert ids["Dee"] == "2026-10-07-c"
