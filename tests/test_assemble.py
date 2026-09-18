from datetime import datetime

from sync.assemble import build_pages
from sync.config import AMSTERDAM
from sync.sheet import read_all
from tests.test_sheet import RESPONSES, reader

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=AMSTERDAM)

HEADER = RESPONSES[0]


def row(when, action, session, name, fmt="", takeaway="", part="", text="", status=""):
    return [when, action, session, name, fmt, "", takeaway, part, text, "", "", "", status, ""]


# The shared data() fixture in test_sheet puts its claim on 2026-10-07, which
# is not a session day: sessions run every other Wednesday from 2026-09-30,
# so the grid is 09-30, 10-14, 10-28, ... This is the same club moved onto
# the grid: page 2026-10-14, open session 2026-10-28, cancelled 2026-11-11.
def club():
    return read_all(reader(
        Responses=[
            HEADER,
            ["2026-09-20 09:00:00", "claim", "2026-10-14", "Ann", "help", "10.1000/xyz",
             "", "", "", "", "", "", "", ""],
            ["2026-10-14 12:10:00", "takeaway", "2026-10-14", "Bo", "", "",
             "The ablation does not separate the mechanisms", "", "", "", "", "", "", ""],
            ["2026-10-15 09:00:00", "page", "2026-10-14", "Ann", "", "", "", "synthesis",
             "We were not convinced", "", "", "", "approved", ""],
            ["2026-10-15 10:00:00", "takeaway", "2026-10-14", "Spam", "", "", "buy things",
             "", "", "", "", "yes", "", ""],
        ],
        Aliases=[["alias", "display name"], ["bo", "Bo de Vries"]],
        **{
            "Open sessions": [["date", "title", "guest", "affiliation", "doi", "length_minutes"],
                              ["2026-10-28", "Guest talk", "A. Author", "Elsewhere", "", "90"]],
            "Skipped weeks": [["date"], ["2026-12-23"]],
            "Session status": [["date", "status"], ["2026-11-11", "cancelled"]],
        },
    ))


# -- the brief's four -------------------------------------------------------

def test_a_session_with_a_takeaway_counts_as_held():
    built = build_pages(club(), {}, NOW)
    page = built.pages["2026-10-14"]
    assert page.session.status == "held"
    assert [t.name for t in page.takeaways] == ["Bo de Vries"]


def test_an_approved_synthesis_is_attached_and_signed():
    built = build_pages(club(), {}, NOW)
    page = built.pages["2026-10-14"]
    assert page.synthesis.text == "We were not convinced"
    assert page.synthesis.name == "Ann"


def test_a_past_session_without_takeaways_stays_unrecorded():
    built = build_pages(club(), {}, NOW)
    page = built.pages["2026-09-30"]
    assert page.session.status == "unrecorded"


def test_pages_exist_for_unclaimed_and_open_sessions_too():
    built = build_pages(club(), {}, NOW)
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
    assert build_pages(club(), {}, NOW).problems == []


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
