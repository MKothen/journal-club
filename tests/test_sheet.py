from datetime import date, datetime

import pytest

from sync.config import AMSTERDAM
from sync.sheet import read_all


class FakeReader:
    def __init__(self, tabs):
        self.tabs = tabs

    def values(self, tab):
        return self.tabs.get(tab, [])


RESPONSES = [
    ["Timestamp", "Action", "Session", "Name", "Format", "DOI", "Takeaway", "Part",
     "Text", "Link", "Why", "hide", "status", "checked by"],
    ["2026-09-20 09:00:00", "claim", "2026-10-14", "Ann", "help", "10.1000/xyz",
     "", "", "", "", "", "", "", ""],
    ["2026-10-14 12:10:00", "takeaway", "2026-10-14", "Bo", "", "",
     "The ablation does not separate the mechanisms", "", "", "", "", "", "", ""],
    ["2026-10-15 09:00:00", "page", "2026-10-14", "Ann", "", "", "", "synthesis",
     "We were not convinced", "", "", "", "approved", ""],
    ["2026-10-15 10:00:00", "takeaway", "2026-10-14", "Spam", "", "", "buy things",
     "", "", "", "", "yes", "", ""],
]

SETTINGS_TAB = [
    ["key", "value"],
    ["club_name", "NCL Journal Club"],
    ["first_session", "2026-09-30"],
    ["session_hour", "11"],
    ["session_minute", "0"],
    ["room", "Lab room"],
    ["horizon_days", "183"],
    ["site_base_url", "https://example.github.io/journal-club"],
    ["form_url", "https://docs.google.com/forms/d/e/FORM/viewform"],
    ["entry_action", "entry.1"],
    ["entry_page", "entry.2"],
]


def data():
    return read_all(FakeReader({
        "Responses": RESPONSES,
        "Settings": SETTINGS_TAB,
        "Open sessions": [["date", "title", "guest", "affiliation", "doi", "length_minutes"],
                          ["2026-10-28", "Guest talk", "A. Author", "Elsewhere", "", "90"]],
        "Skipped weeks": [["date"], ["2026-12-23"]],
        "Session status": [["date", "status"], ["2026-11-11", "cancelled"]],
        "Aliases": [["alias", "display name"], ["bo", "Bo de Vries"]],
    }))


def reader(**tabs):
    """A FakeReader with every required tab valid and empty, overridden by `tabs`."""
    base = {
        "Settings": SETTINGS_TAB,
        "Responses": [],
        "Open sessions": [],
        "Skipped weeks": [],
        "Session status": [],
        "Aliases": [],
    }
    base.update(tabs)
    return FakeReader(base)


def with_settings(**overrides):
    """A copy of SETTINGS_TAB with the given keys replaced."""
    rows = [row[:] for row in SETTINGS_TAB]
    for row in rows:
        if row[0] in overrides:
            row[1] = overrides[row[0]]
    return rows


# -- baseline behaviour (Task 9 brief) --------------------------------------

def test_settings_are_read_from_the_settings_tab():
    assert data().settings.first_session == date(2026, 9, 30)
    assert data().settings.horizon_days == 183


def test_timestamps_are_amsterdam_time():
    claim = data().claims[0]
    assert claim["submitted_at"] == datetime(2026, 9, 20, 9, 0, tzinfo=AMSTERDAM)


def test_hidden_rows_are_dropped():
    assert all("Spam" != c.name for c in data().contributions)


def test_aliases_are_applied_to_names():
    takeaway = [c for c in data().contributions if c.part == "takeaway"][0]
    assert takeaway.name == "Bo de Vries"


def test_approval_status_is_read_per_row():
    synthesis = [c for c in data().contributions if c.part == "synthesis"][0]
    assert synthesis.approved is True


def test_open_sessions_skips_and_status_are_read():
    parsed = data()
    assert parsed.open_sessions[date(2026, 10, 28)]["guest"] == "A. Author"
    assert date(2026, 12, 23) in parsed.skipped
    assert parsed.status[date(2026, 11, 11)] == "cancelled"


def test_a_clean_sheet_reports_no_problems():
    assert data().problems == []


# -- bad input becomes a problem report, never a crash (ruling 1) -----------

def test_an_unrecognised_session_status_is_ignored_and_reported():
    parsed = read_all(reader(**{
        "Session status": [["date", "status"], ["2026-11-04", "maybe"]],
    }))
    assert date(2026, 11, 4) not in parsed.status
    assert any("Session status" in p and "maybe" in p for p in parsed.problems)


def test_a_first_session_not_on_a_wednesday_is_used_but_reported():
    parsed = read_all(reader(Settings=with_settings(first_session="2026-10-01")))  # a Thursday
    assert parsed.settings.first_session == date(2026, 10, 1)
    assert any("Wednesday" in p for p in parsed.problems)


def test_a_non_integer_length_minutes_defaults_to_60_and_is_reported():
    parsed = read_all(reader(**{
        "Open sessions": [["date", "title", "guest", "affiliation", "doi", "length_minutes"],
                          ["2026-10-21", "Guest talk", "A. Author", "Elsewhere", "", "ninety"]],
    }))
    assert parsed.open_sessions[date(2026, 10, 21)]["length_minutes"] == 60
    assert any("length_minutes" in p for p in parsed.problems)


def test_a_responses_row_with_an_unreadable_timestamp_is_skipped_and_reported():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Format", "DOI"],
        ["not-a-timestamp", "claim", "2026-10-07", "Ann", "help", "10.1000/xyz"],
    ]))
    assert parsed.claims == []
    assert any("timestamp" in p for p in parsed.problems)


def test_a_claim_row_with_an_unreadable_session_date_is_skipped_and_reported():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Format", "DOI"],
        ["2026-09-20 09:00:00", "claim", "not-a-date", "Ann", "help", "10.1000/xyz"],
    ]))
    assert parsed.claims == []
    assert any("session date" in p for p in parsed.problems)


def test_a_responses_row_with_an_unknown_action_is_skipped_and_reported():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name"],
        ["2026-09-20 09:00:00", "dance", "2026-10-07", "Ann"],
    ]))
    assert parsed.claims == [] and parsed.contributions == [] and parsed.wishlist == []
    assert any("unknown action" in p for p in parsed.problems)


def test_an_unknown_format_value_is_skipped_and_reported():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Format", "DOI"],
        ["2026-09-20 09:00:00", "claim", "2026-10-07", "Ann", "video call", "10.1000/xyz"],
    ]))
    assert parsed.claims == []
    assert any("unknown format" in p for p in parsed.problems)


def test_an_unknown_part_value_is_skipped_and_reported():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Part", "Text"],
        ["2026-09-20 09:00:00", "page", "2026-10-07", "Ann", "random", "text"],
    ]))
    assert parsed.contributions == []
    assert any("unknown part" in p for p in parsed.problems)


def test_a_missing_settings_key_raises_a_value_error_naming_the_key():
    bad = [row for row in SETTINGS_TAB if row[0] != "club_name"]
    with pytest.raises(ValueError, match="club_name"):
        read_all(reader(Settings=bad))


def test_an_unparseable_settings_value_raises_a_value_error_naming_the_key():
    with pytest.raises(ValueError, match="horizon_days"):
        read_all(reader(Settings=with_settings(horizon_days="not-a-number")))


# -- form labels versus codes (ruling 2) -------------------------------------

def test_action_label_and_code_both_resolve_to_the_claim_code():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Format", "DOI"],
        ["2026-09-20 09:00:00", "Claim a session", "2026-10-07", "Ann", "help", "10.1000/xyz"],
        ["2026-09-20 09:05:00", "claim", "2026-10-14", "Bo", "help", "10.1000/xyz"],
    ]))
    assert [c["name"] for c in parsed.claims] == ["Ann", "Bo"]


def test_format_label_and_code_both_resolve_to_the_help_code():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Format", "DOI"],
        ["2026-09-20 09:00:00", "claim", "2026-10-07", "Ann", "Help me read this", "10.1000/xyz"],
        ["2026-09-20 09:05:00", "claim", "2026-10-14", "Bo", "help", "10.1000/xyz"],
    ]))
    assert [c["fmt"] for c in parsed.claims] == ["help", "help"]


def test_part_label_and_code_both_resolve_to_the_synthesis_code():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Part", "Text", "status"],
        ["2026-09-20 09:00:00", "page", "2026-10-07", "Ann", "Discussion synthesis", "text one", "approved"],
        ["2026-09-20 09:05:00", "page", "2026-10-07", "Bo", "synthesis", "text two", "approved"],
    ]))
    assert [c.part for c in parsed.contributions] == ["synthesis", "synthesis"]


def test_labels_are_matched_case_insensitively_and_with_surrounding_whitespace_trimmed():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Format", "DOI"],
        ["2026-09-20 09:00:00", "  CLAIM A SESSION  ", "2026-10-07", "Ann",
         "  HELP ME READ THIS  ", "10.1000/xyz"],
    ]))
    assert parsed.claims[0]["fmt"] == "help"


# -- duplicate column headers (ruling 3) -------------------------------------

def test_a_duplicate_column_keeps_the_first_non_empty_value_when_the_first_is_blank():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Format", "DOI", "Name"],
        ["2026-09-20 09:00:00", "claim", "2026-10-07", "", "help", "10.1000/xyz", "Ann"],
    ]))
    assert parsed.claims[0]["name"] == "Ann"


def test_a_duplicate_column_keeps_the_first_non_empty_value_when_the_second_is_blank():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Format", "DOI", "Name"],
        ["2026-09-20 09:00:00", "claim", "2026-10-07", "Ann", "help", "10.1000/xyz", ""],
    ]))
    assert parsed.claims[0]["name"] == "Ann"


# -- fix round 1 --------------------------------------------------------------
# I1: a bad date in a hand-edited tab is a problem, not a crash.

def test_a_blank_date_in_skipped_weeks_is_skipped_and_reported():
    parsed = read_all(reader(**{"Skipped weeks": [["date"], [""]]}))
    assert parsed.skipped == set()
    assert any("Skipped weeks" in p for p in parsed.problems)


def test_a_non_iso_date_in_open_sessions_is_skipped_and_reported():
    parsed = read_all(reader(**{
        "Open sessions": [["date", "title", "guest", "affiliation", "doi", "length_minutes"],
                          ["21 Oct", "Guest talk", "A. Author", "Elsewhere", "", "90"]],
    }))
    assert parsed.open_sessions == {}
    assert any("Open sessions" in p and "21 Oct" in p for p in parsed.problems)


def test_a_blank_date_in_session_status_is_skipped_and_reported():
    parsed = read_all(reader(**{"Session status": [["date", "status"], ["", "cancelled"]]}))
    assert parsed.status == {}
    assert any("Session status" in p for p in parsed.problems)


# I2: a takeaway or page row needs a well-formed page id.

def test_a_takeaway_with_a_blank_session_is_skipped_and_reported():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Takeaway"],
        ["2026-09-20 09:00:00", "takeaway", "", "Bo", "a takeaway"],
    ]))
    assert parsed.contributions == []
    assert any("unreadable session" in p for p in parsed.problems)


def test_a_takeaway_with_a_non_page_id_session_is_skipped_and_reported():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Takeaway"],
        ["2026-09-20 09:00:00", "takeaway", "7 Oct", "Bo", "a takeaway"],
    ]))
    assert parsed.contributions == []
    assert any("unreadable session" in p and "7 Oct" in p for p in parsed.problems)


def test_a_well_formed_re_claimed_page_id_is_accepted():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Takeaway"],
        ["2026-09-20 09:00:00", "takeaway", "2026-10-07-2", "Bo", "a takeaway"],
    ]))
    assert [c.page_id for c in parsed.contributions] == ["2026-10-07-2"]


# I3: locale-independent dates and timestamps via Sheets serial numbers.

def test_a_serial_timestamp_parses_to_the_right_amsterdam_datetime():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Format", "DOI"],
        [46285.375, "claim", "2026-10-07", "Ann", "help", "10.1000/xyz"],
    ]))
    assert parsed.claims[0]["submitted_at"] == datetime(2026, 9, 20, 9, 0, tzinfo=AMSTERDAM)


def test_converting_the_same_serial_twice_gives_an_identical_claim_key():
    # Two reads of the "same" cell, with the kind of float noise a real API
    # can introduce between calls without the underlying second changing.
    from sync.claims import claim_key

    def rows_with_serial(serial):
        return [
            ["Timestamp", "Action", "Session", "Name", "Format", "DOI"],
            [serial, "claim", "2026-10-07", "Ann", "help", "10.1000/xyz"],
        ]

    first = read_all(reader(Responses=rows_with_serial(46285.375))).claims[0]
    second = read_all(reader(Responses=rows_with_serial(46285.3750000001))).claims[0]
    assert claim_key(first) == claim_key(second)


def test_a_serial_session_cell_becomes_the_iso_date_page_id():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Takeaway"],
        ["2026-09-20 09:00:00", "takeaway", 46302, "Bo", "a takeaway"],
    ]))
    assert [c.page_id for c in parsed.contributions] == ["2026-10-07"]


def test_a_serial_date_in_skipped_weeks_parses():
    parsed = read_all(reader(**{"Skipped weeks": [["date"], [46379]]}))
    assert date(2026, 12, 23) in parsed.skipped


# I4: only recognised hide values hide a row; an unchecked checkbox (FALSE)
# must not hide everything.

@pytest.mark.parametrize("hidden_value", ["TRUE", "yes", "y", "x", "1", "hide", "Hide"])
def test_a_recognised_true_hide_value_hides_the_row(hidden_value):
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Takeaway", "hide"],
        ["2026-09-20 09:00:00", "takeaway", "2026-10-07", "Bo", "text", hidden_value],
    ]))
    assert parsed.contributions == []
    assert parsed.problems == []


@pytest.mark.parametrize("visible_value", ["FALSE", "no", "0", ""])
def test_a_recognised_false_hide_value_keeps_the_row_visible(visible_value):
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Takeaway", "hide"],
        ["2026-09-20 09:00:00", "takeaway", "2026-10-07", "Bo", "text", visible_value],
    ]))
    assert len(parsed.contributions) == 1
    assert parsed.problems == []


def test_a_boolean_true_hide_cell_hides_the_row():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Takeaway", "hide"],
        ["2026-09-20 09:00:00", "takeaway", "2026-10-07", "Bo", "text", True],
    ]))
    assert parsed.contributions == []
    assert parsed.problems == []


def test_a_boolean_false_hide_cell_keeps_the_row_visible():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Takeaway", "hide"],
        ["2026-09-20 09:00:00", "takeaway", "2026-10-07", "Bo", "text", False],
    ]))
    assert len(parsed.contributions) == 1
    assert parsed.problems == []


def test_an_unrecognised_hide_value_hides_the_row_and_is_reported():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Takeaway", "hide"],
        ["2026-09-20 09:00:00", "takeaway", "2026-10-07", "Bo", "text", "maybe"],
    ]))
    assert parsed.contributions == []
    assert any("hide" in p and "maybe" in p for p in parsed.problems)


# I5: aliasing must never move an already-assigned claim's page.

def test_adding_an_alias_after_a_claim_leaves_its_claim_name_unchanged():
    rows = [
        ["Timestamp", "Action", "Session", "Name", "Format", "DOI"],
        ["2026-09-20 09:00:00", "claim", "2026-10-14", "bo", "help", "10.1000/xyz"],
    ]
    before = read_all(reader(Responses=rows))
    assert before.claims[0]["name"] == "bo"

    after = read_all(reader(
        Responses=rows,
        Aliases=[["alias", "display name"], ["bo", "Bo de Vries"]],
    ))
    assert after.claims[0]["name"] == "bo"
    assert after.aliases["bo"] == "Bo de Vries"


# m2: a valid length_minutes is used as given, not just defaulted to 60.

def test_a_valid_length_minutes_of_90_is_used_as_is():
    assert data().open_sessions[date(2026, 10, 28)]["length_minutes"] == 90


# m3: a tab missing a whole required column raises a clear ValueError.

def test_a_settings_tab_missing_the_value_header_raises_a_value_error():
    with pytest.raises(ValueError, match="Settings"):
        read_all(reader(Settings=[["key"], ["club_name"]]))


def test_an_aliases_tab_missing_the_display_name_header_raises_a_value_error():
    with pytest.raises(ValueError, match="Aliases"):
        read_all(reader(Aliases=[["alias"], ["bo"]]))


# m4: an alias with a blank display name is ignored and reported.

def test_an_alias_with_a_blank_display_name_is_ignored_and_reported():
    parsed = read_all(reader(Aliases=[["alias", "display name"], ["bo", ""]]))
    assert "bo" not in parsed.aliases
    assert any("Aliases" in p and "bo" in p for p in parsed.problems)


# m6: a missing Responses tab is reported, not silently read as empty.

def test_a_missing_responses_tab_records_a_problem():
    fake = FakeReader({"Settings": SETTINGS_TAB})  # no "Responses" key at all
    parsed = read_all(fake)
    assert any("Responses" in p for p in parsed.problems)


# m7: an empty name, an empty takeaway, or an interest row with neither a DOI
# nor a link is a problem, not a silent pass-through.

def test_a_claim_with_an_empty_name_is_skipped_and_reported():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Format", "DOI"],
        ["2026-09-20 09:00:00", "claim", "2026-10-07", "", "help", "10.1000/xyz"],
    ]))
    assert parsed.claims == []
    assert any("empty name" in p for p in parsed.problems)


def test_a_takeaway_with_empty_text_is_skipped_and_reported():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Takeaway"],
        ["2026-09-20 09:00:00", "takeaway", "2026-10-07", "Bo", ""],
    ]))
    assert parsed.contributions == []
    assert any("empty takeaway" in p for p in parsed.problems)


def test_an_interest_row_with_neither_doi_nor_link_is_skipped_and_reported():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "DOI", "Link"],
        ["2026-09-20 09:00:00", "interest", "2026-10-07", "Ann", "", ""],
    ]))
    assert parsed.interest == {}
    assert any("neither a DOI nor a link" in p for p in parsed.problems)


# -- fix round 2 --------------------------------------------------------------
# N1: a numeric date/timestamp far outside the calendar range must not crash.
# An organiser typing a compact date like 20261007 gets a plain number under
# UNFORMATTED_VALUE, and the resulting serial is far too large for a date.

def test_a_large_numeric_timestamp_is_reported_not_crashed():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Format", "DOI"],
        [20261007, "claim", "2026-10-07", "Ann", "help", "10.1000/xyz"],
    ]))
    assert parsed.claims == []
    assert any("timestamp" in p for p in parsed.problems)


def test_a_large_numeric_takeaway_session_is_reported_not_crashed():
    parsed = read_all(reader(Responses=[
        ["Timestamp", "Action", "Session", "Name", "Takeaway"],
        ["2026-09-20 09:00:00", "takeaway", 20261007, "Bo", "a takeaway"],
    ]))
    assert parsed.contributions == []
    assert any("unreadable session" in p for p in parsed.problems)


def test_a_large_numeric_date_in_skipped_weeks_is_reported_not_crashed():
    parsed = read_all(reader(**{"Skipped weeks": [["date"], [23122026]]}))
    assert parsed.skipped == set()
    assert any("Skipped weeks" in p for p in parsed.problems)


def test_a_large_numeric_settings_first_session_is_a_fatal_value_error_naming_the_key():
    with pytest.raises(ValueError, match="first_session"):
        read_all(reader(Settings=with_settings(first_session=20261007)))


# n1: a date serial is the calendar day it falls in, so it floors rather than
# rounds (a timestamp still rounds to the whole second: claim_key depends on
# that, not on the calendar day).

def test_a_fractional_date_serial_floors_to_its_calendar_day():
    parsed = read_all(reader(**{"Skipped weeks": [["date"], [46302.75]]}))
    assert date(2026, 10, 7) in parsed.skipped


# The Settings `0` fix (require() no longer treats 0 as missing): a mutant
# that restores the old falsy check passes every other test in this file.

def test_a_settings_session_minute_of_integer_zero_is_read_as_zero():
    parsed = read_all(reader(Settings=with_settings(session_minute=0)))
    assert parsed.settings.session_minute == 0


def test_a_blank_settings_session_minute_is_still_a_fatal_value_error():
    with pytest.raises(ValueError, match="session_minute"):
        read_all(reader(Settings=with_settings(session_minute="")))
