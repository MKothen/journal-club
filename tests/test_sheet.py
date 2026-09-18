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
    ["2026-09-20 09:00:00", "claim", "2026-10-07", "Ann", "help", "10.1000/xyz",
     "", "", "", "", "", "", "", ""],
    ["2026-10-07 12:10:00", "takeaway", "2026-10-07", "Bo", "", "",
     "The ablation does not separate the mechanisms", "", "", "", "", "", "", ""],
    ["2026-10-08 09:00:00", "page", "2026-10-07", "Ann", "", "", "", "synthesis",
     "We were not convinced", "", "", "", "approved", ""],
    ["2026-10-08 10:00:00", "takeaway", "2026-10-07", "Spam", "", "", "buy things",
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
                          ["2026-10-21", "Guest talk", "A. Author", "Elsewhere", "", "90"]],
        "Skipped weeks": [["date"], ["2026-12-23"]],
        "Session status": [["date", "status"], ["2026-11-04", "cancelled"]],
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
    assert parsed.open_sessions[date(2026, 10, 21)]["guest"] == "A. Author"
    assert date(2026, 12, 23) in parsed.skipped
    assert parsed.status[date(2026, 11, 4)] == "cancelled"


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
