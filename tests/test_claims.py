from datetime import date, datetime

import pytest

from sync.claims import claim_key, resolve_claims
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
OCT_7 = date(2026, 10, 7)


def starts(sessions):
    """Every session starts at 11:00 Amsterdam time, as in the fixture's Settings."""
    return {s.day: datetime(s.day.year, s.day.month, s.day.day, 11, 0, tzinfo=AMSTERDAM)
            for s in sessions}


def resolve(rows, assigned=None, refused=None, sessions=SESSIONS):
    return resolve_claims(sessions, rows, dict(assigned or {}), set(refused or ()),
                          starts(sessions))


def test_a_long_claim_gets_the_bare_date_as_its_page_id():
    result = resolve([claim("Max", OCT_7)])
    assert [s.page_id for s in result.slots] == ["2026-10-07"]


def test_two_short_claims_share_a_session_as_a_and_b():
    rows = [
        claim("Ann", OCT_7, "short", at(1, 9)),
        claim("Bo", OCT_7, "short", at(2, 9)),
    ]
    result = resolve(rows)
    assert [s.page_id for s in result.slots] == ["2026-10-07-a", "2026-10-07-b"]


def test_the_earliest_claim_wins_and_the_later_one_is_rejected():
    rows = [
        claim("Late", OCT_7, "full", at(3, 9)),
        claim("Early", OCT_7, "full", at(1, 9)),
    ]
    result = resolve(rows)
    assert [s.presenter for s in result.slots] == ["Early"]
    assert result.rejections[0].name == "Late"
    assert result.rejections[0].reason == "taken"


def test_a_claim_on_an_open_session_is_rejected():
    result = resolve([claim("Max", date(2026, 10, 21))])
    assert result.slots == []
    assert result.rejections[0].reason == "not-claimable"


def test_a_claim_on_an_unknown_date_is_rejected():
    result = resolve([claim("Max", date(2026, 10, 8))])
    assert result.rejections[0].reason == "not-claimable"


def test_ids_are_frozen_once_assigned():
    rows = [claim("Ann", OCT_7, "short", at(1, 9))]
    first = resolve(rows)
    rows.insert(0, claim("Bo", OCT_7, "short", at(2, 9)))
    second = resolve(rows, first.assigned)
    ids = {s.presenter: s.page_id for s in second.slots}
    assert ids["Ann"] == "2026-10-07-a"
    assert ids["Bo"] == "2026-10-07-b"


def test_a_hidden_claim_retires_its_id_and_the_survivor_keeps_its_own():
    rows = [
        claim("Ann", OCT_7, "short", at(1, 9)),
        claim("Bo", OCT_7, "short", at(2, 9)),
    ]
    first = resolve(rows)
    rows[0] = claim("Ann", OCT_7, "short", at(1, 9), hidden=True)
    second = resolve(rows, first.assigned)
    assert [s.page_id for s in second.slots] == ["2026-10-07-b"]


def test_a_third_short_claim_is_rejected_and_burns_no_id():
    rows = [
        claim("Ann", OCT_7, "short", at(1, 9)),
        claim("Bo", OCT_7, "short", at(2, 9)),
        claim("Cy", OCT_7, "short", at(3, 9)),
    ]
    result = resolve(rows)
    assert [s.page_id for s in result.slots] == ["2026-10-07-a", "2026-10-07-b"]
    assert result.rejections[0].name == "Cy"
    assert result.rejections[0].reason == "taken"
    assert claim_key(rows[2]) not in result.assigned


def test_a_full_claim_after_a_short_claim_on_the_same_session_is_rejected():
    rows = [
        claim("Ann", OCT_7, "short", at(1, 9)),
        claim("Bo", OCT_7, "full", at(2, 9)),
    ]
    result = resolve(rows)
    assert [s.presenter for s in result.slots] == ["Ann"]
    assert [s.page_id for s in result.slots] == ["2026-10-07-a"]
    assert result.rejections[0].name == "Bo"
    assert result.rejections[0].reason == "taken"


def test_a_released_long_claim_frees_capacity_but_not_its_id():
    rows = [claim("Ann", OCT_7, "full", at(1, 9))]
    first = resolve(rows)
    assert [s.page_id for s in first.slots] == ["2026-10-07"]

    rows = [
        claim("Ann", OCT_7, "full", at(1, 9), hidden=True),
        claim("Carl", OCT_7, "full", at(2, 9)),
    ]
    second = resolve(rows, first.assigned)
    assert [s.presenter for s in second.slots] == ["Carl"]
    assert [s.page_id for s in second.slots] == ["2026-10-07-2"]


def test_a_released_short_claim_frees_capacity_and_gets_the_next_free_id():
    rows = [
        claim("Ann", OCT_7, "short", at(1, 9)),
        claim("Bo", OCT_7, "short", at(2, 9)),
    ]
    first = resolve(rows)
    assert [s.page_id for s in first.slots] == ["2026-10-07-a", "2026-10-07-b"]

    rows = [
        claim("Ann", OCT_7, "short", at(1, 9), hidden=True),
        claim("Bo", OCT_7, "short", at(2, 9)),
        claim("Dee", OCT_7, "short", at(3, 9)),
    ]
    second = resolve(rows, first.assigned)
    ids = {s.presenter: s.page_id for s in second.slots}
    assert ids["Bo"] == "2026-10-07-b"
    assert ids["Dee"] == "2026-10-07-c"


# Task 10 R3: a rejection notice is logged under its claim's key, so the
# rejection must carry that key.

def test_a_rejection_carries_the_key_of_the_claim_it_rejects():
    rows = [
        claim("Early", OCT_7, "full", at(1, 9)),
        claim("Late", OCT_7, "full", at(3, 9)),
        claim("Max", date(2026, 10, 21), "full", at(4, 9)),
    ]
    result = resolve(rows)
    assert [r.key for r in result.rejections] == [claim_key(rows[1]), claim_key(rows[2])]


# -- final review D1: a claim is judged as of when it was made ------------------

@pytest.mark.parametrize("hour", [11, 13], ids=["at the start", "after it"])
def test_a_claim_made_once_its_session_has_started_is_refused_even_on_the_day(hour):
    late = claim("Dee", OCT_7, when=datetime(2026, 10, 7, hour, 0, tzinfo=AMSTERDAM))
    result = resolve([late])
    assert result.slots == []
    assert [(r.name, r.reason) for r in result.rejections] == [("Dee", "not-claimable")]
    assert result.refused == {claim_key(late)}


def test_a_claim_made_a_minute_before_its_session_is_placed():
    rows = [claim("Dee", OCT_7, when=datetime(2026, 10, 7, 10, 59, tzinfo=AMSTERDAM))]
    assert [s.page_id for s in resolve(rows).slots] == ["2026-10-07"]


def test_a_claim_made_before_its_session_but_first_seen_after_it_is_placed():
    # The automation was down from before the claim until after the session,
    # so the session is already unrecorded when the claim is first resolved.
    past = [Session(day=OCT_7, kind="regular", status="unrecorded")]
    rows = [claim("Ann", OCT_7, when=datetime(2026, 10, 6, 9, 0, tzinfo=AMSTERDAM))]
    result = resolve(rows, sessions=past)
    assert [s.page_id for s in result.slots] == ["2026-10-07"]
    assert result.rejections == []


# -- final review D3: cancelling a claimed session ---------------------------------

CANCELLED = [Session(day=OCT_7, kind="regular", status="cancelled"), SESSIONS[1]]


def test_a_placed_claim_on_a_cancelled_session_keeps_its_slot_without_a_notice():
    rows = [claim("Ann", OCT_7)]
    first = resolve(rows)
    second = resolve(rows, first.assigned, first.refused, sessions=CANCELLED)
    assert [(s.presenter, s.page_id) for s in second.slots] == [("Ann", "2026-10-07")]
    assert second.rejections == []


def test_a_new_claim_on_a_cancelled_session_is_refused():
    result = resolve([claim("Ann", OCT_7)], sessions=CANCELLED)
    assert result.slots == []
    assert [r.reason for r in result.rejections] == ["not-claimable"]


@pytest.mark.parametrize("sessions", [
    [Session(day=OCT_7, kind="open", status="scheduled"), SESSIONS[1]],
    [SESSIONS[1]],
], ids=["made an open session", "made a skipped week"])
def test_a_placed_claim_whose_date_stops_being_a_regular_session_leaves_no_notice(sessions):
    rows = [claim("Ann", OCT_7)]
    first = resolve(rows)
    second = resolve(rows, first.assigned, first.refused, sessions=sessions)
    assert second.slots == [] and second.rejections == []
    assert second.assigned == first.assigned


# -- final review D7: a refusal is permanent -----------------------------------------

def test_a_refused_claim_stays_refused_when_the_session_is_released():
    ann = claim("Ann", OCT_7, when=at(1, 9))
    bo = claim("Bo", OCT_7, when=at(2, 9))
    first = resolve([ann, bo])
    assert [(r.name, r.reason) for r in first.rejections] == [("Bo", "taken")]

    # Ann's row is hidden, and Cy claims the released session.
    cy = claim("Cy", OCT_7, when=at(3, 9))
    second = resolve([bo, cy], first.assigned, first.refused)
    assert second.rejections == []
    assert [(s.presenter, s.page_id) for s in second.slots] == [("Cy", "2026-10-07-2")]
    assert second.refused == {claim_key(bo)}


@pytest.mark.parametrize("sessions", [
    [SESSIONS[1]],
    [Session(day=OCT_7, kind="regular", status="cancelled"), SESSIONS[1]],
    [Session(day=OCT_7, kind="open", status="scheduled"), SESSIONS[1]],
], ids=["beyond the horizon or skipped", "cancelled", "an open session"])
def test_a_claim_refused_as_not_claimable_stays_refused_once_the_date_is_claimable(sessions):
    rows = [claim("Ann", OCT_7)]
    first = resolve(rows, sessions=sessions)
    assert [r.reason for r in first.rejections] == ["not-claimable"]

    second = resolve(rows, first.assigned, first.refused)
    assert second.slots == [] and second.rejections == []


# -- final review I2: a placed claim is never bumped ---------------------------------

def test_an_older_row_that_becomes_valid_never_bumps_a_placed_claim():
    fin = claim("Fin", OCT_7, when=at(2, 9))
    first = resolve([fin])
    assert [s.page_id for s in first.slots] == ["2026-10-07"]

    # An organiser fixes an earlier row the problem digest reported.
    eve = claim("Eve", OCT_7, when=at(1, 9))
    second = resolve([eve, fin], first.assigned, first.refused)
    assert [(s.presenter, s.page_id) for s in second.slots] == [("Fin", "2026-10-07")]
    assert [(r.name, r.reason) for r in second.rejections] == [("Eve", "taken")]


# -- Task 3 minor: rows sharing a claim key ------------------------------------------

@pytest.mark.parametrize("fmt, page_id", [("full", "2026-10-07"), ("short", "2026-10-07-a")])
def test_two_rows_with_one_key_are_one_claim(fmt, page_id):
    ann = claim("Ann", OCT_7, fmt, at(1, 9))
    result = resolve([ann, dict(ann)])
    assert [s.page_id for s in result.slots] == [page_id]
    assert result.rejections == []
