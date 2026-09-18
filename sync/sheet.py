"""Read the Google Sheet into plain Python. The reader is a protocol so the
tests never touch the network.

Everything people submit arrives through one branching form and lands in one
Responses tab, alongside tabs organisers edit by hand (Settings, Open
sessions, Skipped weeks, Session status, Aliases). This is where human input
enters the system, so it is where malformed input must be caught: one
mistyped cell must never crash the unattended sync job or silently publish a
wrong state. Anything that can be worked around is recorded as a
plain-language problem on `SheetData.problems` and the offending row (or
value) is skipped or defaulted. Only a broken Settings tab is fatal, since
nothing downstream can run without it.
"""

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

import gspread

from sync.config import ACTION_LABELS, AMSTERDAM, FORMAT_LABELS, PART_LABELS, Settings
from sync.model import Contribution, WishlistEntry
from sync.papers import normalise_doi

WEDNESDAY = 2


class TabReader(Protocol):
    def values(self, tab: str) -> list[list[str]]:
        ...


@dataclass
class SheetData:
    settings: Settings
    problems: list[str] = field(default_factory=list)
    skipped: set[date] = field(default_factory=set)
    open_sessions: dict[date, dict] = field(default_factory=dict)
    status: dict[date, str] = field(default_factory=dict)
    claims: list[dict] = field(default_factory=list)
    contributions: list[Contribution] = field(default_factory=list)
    wishlist: list[WishlistEntry] = field(default_factory=list)
    interest: dict[str, int] = field(default_factory=dict)


def _rows(values: list[list[str]]) -> list[dict]:
    """Header row (case-insensitively) maps to the data rows below it. A
    header repeated across several form sections (several "Name" questions,
    say) keeps the first non-empty cell under that key rather than letting a
    later blank column overwrite an earlier filled one."""
    if not values:
        return []
    header = [h.strip().lower() for h in values[0]]
    out = []
    for row in values[1:]:
        padded = list(row) + [""] * (len(header) - len(row))
        record: dict[str, str] = {}
        for key, cell in zip(header, padded):
            cell = cell.strip()
            if not record.get(key):
                record[key] = cell
        out.append(record)
    return out


def _timestamp(raw: str) -> datetime:
    return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=AMSTERDAM)


def _date(raw: str) -> date:
    return date.fromisoformat(raw)


def _label_to_code(raw: str, labels: dict[str, str]) -> str | None:
    """Map a form option back to its code, matching the visible label or the
    bare code, case-insensitively and ignoring surrounding whitespace. A form
    prefills the label (Google Forms needs the option's exact visible text);
    the rest of the system only ever sees the code."""
    value = raw.strip().lower()
    if not value:
        return None
    if value in labels:
        return value
    for code, label in labels.items():
        if label.strip().lower() == value:
            return code
    return None


def read_all(reader: TabReader) -> SheetData:
    settings, problems = _settings(_rows(reader.values("Settings")))
    aliases = {
        row["alias"].lower(): row["display name"]
        for row in _rows(reader.values("Aliases"))
        if row.get("alias")
    }
    data = SheetData(settings=settings, problems=problems)

    for row in _rows(reader.values("Skipped weeks")):
        data.skipped.add(_date(row["date"]))

    for i, row in enumerate(_rows(reader.values("Open sessions")), start=2):
        length_minutes, problem = _length_minutes(row.get("length_minutes", ""), i)
        if problem:
            data.problems.append(problem)
        data.open_sessions[_date(row["date"])] = {
            "title": row.get("title") or None,
            "guest": row.get("guest") or None,
            "affiliation": row.get("affiliation") or None,
            "doi": normalise_doi(row.get("doi")),
            "length_minutes": length_minutes,
        }

    for i, row in enumerate(_rows(reader.values("Session status")), start=2):
        raw_status = row.get("status", "")
        status = raw_status.strip().lower()
        if status not in ("cancelled", "held"):
            data.problems.append(
                f"Session status row {i} has status '{raw_status}', which is "
                "neither 'cancelled' nor 'held'; ignoring it."
            )
            continue
        data.status[_date(row["date"])] = status

    for i, row in enumerate(_rows(reader.values("Responses")), start=2):
        if row.get("hide"):
            continue
        _read_response_row(row, i, aliases, data)

    return data


def _length_minutes(raw: str, row_num: int) -> tuple[int, str | None]:
    raw = (raw or "").strip()
    if not raw:
        return 60, None
    try:
        return int(raw), None
    except ValueError:
        problem = (
            f"Open sessions row {row_num} has length_minutes '{raw}', which "
            "is not a whole number; using 60 instead."
        )
        return 60, problem


def _read_response_row(row: dict, row_num: int, aliases: dict[str, str], data: SheetData) -> None:
    raw_timestamp = row.get("timestamp", "")
    try:
        when = _timestamp(raw_timestamp)
    except ValueError:
        data.problems.append(
            f"Responses row {row_num} has an unreadable timestamp "
            f"'{raw_timestamp}'; skipping the row."
        )
        return

    raw_action = row.get("action", "")
    action = _label_to_code(raw_action, ACTION_LABELS)
    if action is None:
        data.problems.append(
            f"Responses row {row_num} has an unknown action '{raw_action}'; "
            "skipping the row."
        )
        return

    name = aliases.get(row.get("name", "").lower(), row.get("name", ""))

    if action == "claim":
        raw_session = row.get("session", "")
        try:
            day = _date(raw_session)
        except ValueError:
            data.problems.append(
                f"Responses row {row_num} has an unreadable session date "
                f"'{raw_session}'; skipping the row."
            )
            return
        raw_format = row.get("format", "")
        fmt = _label_to_code(raw_format, FORMAT_LABELS)
        if fmt is None:
            data.problems.append(
                f"Responses row {row_num} has an unknown format "
                f"'{raw_format}'; skipping the row."
            )
            return
        data.claims.append({
            "name": name, "day": day, "fmt": fmt,
            "doi": normalise_doi(row.get("doi")), "paper_title": row.get("text") or None,
            "paper_link": row.get("link") or None, "submitted_at": when, "hidden": False,
        })
    elif action == "takeaway":
        data.contributions.append(Contribution(
            page_id=row.get("session", ""), part="takeaway", name=name,
            text=row.get("takeaway", ""), link=None, submitted_at=when,
            approved=True, checked_by=None,
        ))
    elif action == "page":
        raw_part = row.get("part", "")
        part = _label_to_code(raw_part, PART_LABELS)
        if part is None:
            data.problems.append(
                f"Responses row {row_num} has an unknown part '{raw_part}'; "
                "skipping the row."
            )
            return
        data.contributions.append(Contribution(
            page_id=row.get("session", ""), part=part, name=name,
            text=row.get("text", ""), link=row.get("link") or None, submitted_at=when,
            approved=row.get("status", "").lower() == "approved",
            checked_by=row.get("checked by") or None,
        ))
    elif action == "wishlist":
        data.wishlist.append(WishlistEntry(
            doi=normalise_doi(row.get("doi")), paper_title=row.get("text") or None,
            paper_link=row.get("link") or None, name=name, why=row.get("why", ""),
            submitted_at=when,
        ))
    elif action == "interest":
        key = normalise_doi(row.get("doi")) or row.get("link", "")
        data.interest[key] = data.interest.get(key, 0) + 1


def _settings(rows: list[dict]) -> tuple[Settings, list[str]]:
    """A malformed Settings tab is the one fatal case: nothing downstream can
    run without it, so a missing key or an unparseable required value raises
    a ValueError naming the key rather than being recorded as a problem."""
    values = {row["key"]: row["value"] for row in rows if row.get("key")}
    problems: list[str] = []

    def require(key: str) -> str:
        value = values.get(key, "")
        if not value:
            raise ValueError(f"Settings is missing a value for '{key}'")
        return value

    def require_int(key: str) -> int:
        raw = require(key)
        try:
            return int(raw)
        except ValueError:
            raise ValueError(f"Settings key '{key}' must be a whole number, got '{raw}'") from None

    def require_date(key: str) -> date:
        raw = require(key)
        try:
            return date.fromisoformat(raw)
        except ValueError:
            raise ValueError(f"Settings key '{key}' must be a date (YYYY-MM-DD), got '{raw}'") from None

    first_session = require_date("first_session")
    if first_session.weekday() != WEDNESDAY:
        problems.append(
            f"Settings first_session '{first_session.isoformat()}' does not "
            "fall on a Wednesday; using it anyway."
        )

    settings = Settings(
        club_name=require("club_name"),
        first_session=first_session,
        session_hour=require_int("session_hour"),
        session_minute=require_int("session_minute"),
        room=require("room"),
        horizon_days=require_int("horizon_days"),
        site_base_url=require("site_base_url").rstrip("/"),
        form_url=require("form_url"),
        entry_action=require("entry_action"),
        entry_page=require("entry_page"),
    )
    return settings, problems


class GspreadReader:
    """Read-only adapter. Not unit-tested; exercised by the smoke test in Task 14."""

    def __init__(self, sheet_id: str, credentials_json: str):
        client = gspread.service_account_from_dict(json.loads(credentials_json))
        self.sheet = client.open_by_key(sheet_id)

    def values(self, tab: str) -> list[list[str]]:
        try:
            return self.sheet.worksheet(tab).get_all_values()
        except gspread.WorksheetNotFound:
            return []
