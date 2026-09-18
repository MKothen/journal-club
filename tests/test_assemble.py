from datetime import datetime

import pytest

from sync.assemble import build_pages
from sync.config import AMSTERDAM
from sync.sheet import read_all
from tests.test_sheet import RESPONSES, data, reader

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=AMSTERDAM)

HEADER = RESPONSES[0]


def row(when, action, session, name, fmt="", takeaway="", part="", text="", status=""):
    return [when, action, session, name, fmt, "", takeaway, part, text, "", "", "", status, ""]


# -- the brief's four -------------------------------------------------------

def test_a_session_with_a_takeaway_counts_as_held():
    built = build_pages(data(), {}, NOW)
    page = built.pages["2026-10-14"]
    assert page.session.status == "held"
    assert [t.name for t in page.takeaways] == ["Bo de Vries"]


def test_an_approved_synthesis_is_attached_and_signed():
    built = build_pages(data(), {}, NOW)
    page = built.pages["2026-10-14"]
    assert page.synthesis.text == "We were not convinced"
    assert page.synthesis.name == "Ann"


def test_a_past_session_without_takeaways_stays_unrecorded():
    built = build_pages(data(), {}, NOW)
    page = built.pages["2026-09-30"]
    assert page.session.status == "unrecorded"


def test_pages_exist_for_unclaimed_and_open_sessions_too():
    built = build_pages(data(), {}, NOW)
    assert "2026-10-28" in built.pages
    assert built.pages["2026-10-28"].session.kind == "open"


# -- held-ness never overrides an organiser's mark ---------------------------

def test_a_cancelled_session_stays_cancelled_even_with_a_takeaway():
    parsed = read_all(reader(
        Responses=[HEADER, row("2026-11-11 12:00:00", "takeaway", "2026-11-11", "Bo",
                               takeaway="It was cancelled but I wrote this anyway")],
        **{"Session status": [["date", "status"], ["2026-11-11", "cancelled"]]},
    ))
    built = build_pages(parsed, {}, datetime(2026, 11, 15, 12, 0, tzinfo=AMSTERDAM))
    assert built.pages["2026-11-11"].session.status == "cancelled"


# -- a takeaway marks a session held only once it has started ----------------

def test_a_takeaway_on_a_future_session_attaches_but_leaves_it_scheduled():
    parsed = read_all(reader(Responses=[
        HEADER, row("2026-10-19 12:00:00", "takeaway", "2026-11-25", "Bo", takeaway="Early"),
    ]))
    page = build_pages(parsed, {}, NOW).pages["2026-11-25"]
    assert page.session.status == "scheduled"
    assert [t.text for t in page.takeaways] == ["Early"]


def test_a_takeaway_counts_from_the_moment_the_session_starts():
    parsed = read_all(reader(Responses=[
        HEADER, row("2026-10-28 10:00:00", "takeaway", "2026-10-28", "Bo", takeaway="On the day"),
    ]))
    before = datetime(2026, 10, 28, 10, 59, tzinfo=AMSTERDAM)
    at_start = datetime(2026, 10, 28, 11, 0, tzinfo=AMSTERDAM)
    assert build_pages(parsed, {}, before).pages["2026-10-28"].session.status == "scheduled"
    assert build_pages(parsed, {}, at_start).pages["2026-10-28"].session.status == "held"


# -- R6: a contribution naming a page that does not exist is reported -------

def test_a_takeaway_for_a_page_that_does_not_exist_is_reported_as_a_problem():
    parsed = read_all(reader(
        Responses=[HEADER, row("2026-10-09 12:00:00", "takeaway", "2026-10-09", "Bo",
                               takeaway="Wrong date on the QR code")],
        Aliases=[["alias", "display name"], ["bo", "Bo de Vries"]],
    ))
    built = build_pages(parsed, {}, NOW)
    assert "Takeaway from Bo de Vries names page 2026-10-09, which does not exist" in built.problems


def test_an_unapproved_part_for_a_missing_page_is_reported_too():
    parsed = read_all(reader(
        Responses=[HEADER, row("2026-10-09 12:00:00", "page", "2026-10-14-z", "Ann",
                               part="synthesis", text="We were not convinced")],
    ))
    built = build_pages(parsed, {}, NOW)
    assert any("2026-10-14-z" in p and "Ann" in p for p in built.problems)


def test_contributions_that_found_their_page_raise_no_problem():
    assert build_pages(data(), {}, NOW).problems == []


# -- R7: aliases change the name shown, never the page id --------------------

def test_an_alias_added_after_a_claim_changes_the_presenter_but_not_the_page_id():
    claim = [HEADER, row("2026-09-20 09:00:00", "claim", "2026-10-14", "bo", fmt="full")]

    before = build_pages(read_all(reader(Responses=claim)), {}, NOW)
    assert before.pages["2026-10-14"].slot.presenter == "bo"

    after = build_pages(
        read_all(reader(Responses=claim, Aliases=[["alias", "display name"], ["bo", "Bo de Vries"]])),
        before.assigned, NOW,
    )
    assert list(after.assigned.values()) == ["2026-10-14"]
    assert after.pages["2026-10-14"].slot.presenter == "Bo de Vries"
    assert [s.presenter for s in after.slots] == ["Bo de Vries"]


def test_a_rejected_claimant_is_named_by_their_alias_but_keyed_by_their_claim_name():
    rows = [HEADER,
            row("2026-09-20 09:00:00", "claim", "2026-10-14", "Ann", fmt="full"),
            row("2026-09-21 09:00:00", "claim", "2026-10-14", "bo", fmt="full")]
    built = build_pages(
        read_all(reader(Responses=rows, Aliases=[["alias", "display name"], ["bo", "Bo de Vries"]])),
        {}, NOW,
    )
    assert [r.name for r in built.rejections] == ["Bo de Vries"]
    assert built.rejections[0].key.endswith("|bo")


# -- final review D1: a claim made once a same-day chat has started ------------------

def test_a_claim_made_after_a_same_day_chat_started_leaves_the_chat_its_page():
    # An open paper chat is held at 11:00 and gets a takeaway. Dee claims the
    # session at 13:00 that day, and the 15:17 run resolves the claim.
    parsed = read_all(reader(Responses=[
        HEADER,
        row("2026-10-14 12:10:00", "takeaway", "2026-10-14", "Cy", takeaway="We read one figure"),
        row("2026-10-14 13:00:00", "claim", "2026-10-14", "Dee", fmt="full"),
    ]))
    built = build_pages(parsed, {}, datetime(2026, 10, 14, 15, 17, tzinfo=AMSTERDAM))
    page = built.pages["2026-10-14"]
    assert page.slot is None
    assert [t.name for t in page.takeaways] == ["Cy"]
    assert page.session.status == "held"
    assert [(r.name, r.reason) for r in built.rejections] == [("Dee", "not-claimable")]
    assert built.assigned == {}


# -- final review D3: cancelling a claimed session keeps its page --------------------

CLAIMED_LATER = [HEADER, row("2026-09-20 09:00:00", "claim", "2026-11-25", "Ann", fmt="full")]


def test_cancelling_a_claimed_session_keeps_its_page_marked_cancelled_and_sends_no_notice():
    first = build_pages(read_all(reader(Responses=CLAIMED_LATER)), {}, NOW)
    cancelled = read_all(reader(
        Responses=CLAIMED_LATER,
        **{"Session status": [["date", "status"], ["2026-11-25", "cancelled"]]},
    ))
    second = build_pages(cancelled, first.assigned, NOW, first.refused)
    page = second.pages["2026-11-25"]
    assert page.slot.presenter == "Ann"
    assert page.session.status == "cancelled"
    assert second.rejections == []
    assert second.assigned == first.assigned


# -- final review D7: a claim refused beyond the horizon stays refused ---------------

def test_a_claim_refused_beyond_the_horizon_stays_refused_once_the_date_is_in_range():
    # With horizon_days 183, 2027-05-12 is beyond the horizon on 20 October
    # 2026 and within it on 1 January 2027.
    rows = [HEADER, row("2026-10-19 09:00:00", "claim", "2027-05-12", "Ann", fmt="full")]
    parsed = read_all(reader(Responses=rows))
    first = build_pages(parsed, {}, NOW)
    assert [r.reason for r in first.rejections] == ["not-claimable"]

    later = datetime(2027, 1, 1, 12, 0, tzinfo=AMSTERDAM)
    second = build_pages(parsed, first.assigned, later, first.refused)
    assert "2027-05-12" in {s.day.isoformat() for s in second.sessions}
    assert second.slots == [] and second.rejections == []
    assert second.pages["2027-05-12"].slot is None


# -- final review D2: an unclaimed session's page never takes a retired id ----------

def test_a_released_claims_id_is_never_reused_by_the_unclaimed_sessions_page():
    ann = row("2026-09-20 09:00:00", "claim", "2026-10-14", "Ann", fmt="full")
    takeaway = row("2026-10-14 12:10:00", "takeaway", "2026-10-14", "Ann", takeaway="My notes")
    first = build_pages(read_all(reader(Responses=[HEADER, ann, takeaway])), {}, NOW)
    assert first.pages["2026-10-14"].slot.presenter == "Ann"

    # Ann's claim is hidden, which releases the session and retires its id.
    hidden = ann[:11] + ["yes"] + ann[12:]
    second = build_pages(read_all(reader(Responses=[HEADER, hidden, takeaway])),
                         first.assigned, NOW, first.refused)
    assert "2026-10-14" not in second.pages
    page = second.pages["2026-10-14-2"]
    assert page.slot is None and page.takeaways == []
    assert "Takeaway from Ann names page 2026-10-14, which does not exist" in second.problems


# -- final review I5: held is a session's status, not a page's -----------------------

def test_a_takeaway_on_one_short_slot_marks_the_whole_session_held():
    parsed = read_all(reader(Responses=[
        HEADER,
        row("2026-09-20 09:00:00", "claim", "2026-10-14", "Ann", fmt="short"),
        row("2026-09-21 09:00:00", "claim", "2026-10-14", "Bo", fmt="short"),
        row("2026-10-14 12:10:00", "takeaway", "2026-10-14-a", "Cy", takeaway="Only on a"),
    ]))
    built = build_pages(parsed, {}, NOW)
    assert built.pages["2026-10-14-a"].session.status == "held"
    assert built.pages["2026-10-14-b"].session.status == "held"
    assert [s.status for s in built.sessions if s.day.isoformat() == "2026-10-14"] == ["held"]


# -- Task 9 minor b: a date off the session grid is reported, not ignored -----------

OFF_GRID = {
    "Skipped weeks": [["date"], ["2026-10-13"]],
    "Session status": [["date", "status"], ["2026-10-13", "cancelled"]],
    "Open sessions": [["date", "title", "guest", "affiliation", "doi", "length_minutes"],
                      ["2026-10-13", "Guest talk", "A. Author", "", "", ""]],
}


@pytest.mark.parametrize("tab", list(OFF_GRID))
def test_a_date_that_is_not_a_session_date_is_reported_once(tab):
    # 13 October is the Tuesday before a session: a mistyped cancellation
    # would otherwise do nothing, silently, and the reminder would still go out.
    built = build_pages(read_all(reader(**{tab: OFF_GRID[tab]})), {}, NOW)
    assert len(built.problems) == 1
    assert tab in built.problems[0] and "2026-10-13" in built.problems[0]


@pytest.mark.parametrize("day", ["2026-09-23", "2027-06-02"], ids=["before the first", "beyond the horizon"])
def test_a_date_outside_the_schedule_is_not_reported(day):
    parsed = read_all(reader(**{"Skipped weeks": [["date"], [day]]}))
    assert build_pages(parsed, {}, NOW).problems == []
