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

`GspreadReader` asks Sheets for UNFORMATTED_VALUE/SERIAL_NUMBER rather than
the displayed text, so dates and timestamps arrive as Sheets serial day
numbers (days since 1899-12-30, in the spreadsheet's own time zone) instead
of a string formatted in the sheet's locale -- a Dutch-locale sheet would
otherwise write "17-9-2026 21:05:33" and every response would fail to parse.
Other cells may likewise arrive as numbers or booleans rather than strings.
"""

import json
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Protocol

import gspread

from sync.config import ACTION_LABELS, AMSTERDAM, FORMAT_LABELS, PART_LABELS, Settings
from sync.model import Contribution, WishlistEntry
from sync.papers import normalise_doi

WEDNESDAY = 2
EXCEL_EPOCH = datetime(1899, 12, 30)

# A page id is a session date optionally followed by a claims.py suffix: a
# short-slot letter (a, b, ...) or a re-claimed-slot number (-2, -3, ...).
PAGE_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:-(?:[a-z]|\d+))?$")

_HIDE_TRUE = {"true", "yes", "y", "x", "1", "hide"}
_HIDE_FALSE = {"false", "no", "0", ""}


class TabReader(Protocol):
    def values(self, tab: str) -> list[list[object]]:
        ...


@dataclass
class SheetData:
    settings: Settings
    problems: list[str] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)
    skipped: set[date] = field(default_factory=set)
    open_sessions: dict[date, dict] = field(default_factory=dict)
    status: dict[date, str] = field(default_factory=dict)
    claims: list[dict] = field(default_factory=list)
    contributions: list[Contribution] = field(default_factory=list)
    wishlist: list[WishlistEntry] = field(default_factory=list)
    interest: dict[str, int] = field(default_factory=dict)


def _str(value: object) -> str:
    """Coerce a cell to text. `_rows` already strips string cells; a cell
    Sheets auto-typed as a number or boolean arrives here unconverted."""
    if isinstance(value, str):
        return value
    return str(value)


def _opt_str(row: dict, key: str) -> str | None:
    value = _str(row.get(key, ""))
    return value or None


def _rows(values: list[list[object]]) -> list[dict]:
    """Header row (case-insensitively) maps to the data rows below it. A
    header repeated across several form sections (several "Name" questions,
    say) keeps the first non-empty cell under that key rather than letting a
    later blank column overwrite an earlier filled one. String cells are
    stripped; a number or boolean cell is left as Sheets sent it."""
    if not values:
        return []
    header = [_str(h).strip().lower() for h in values[0]]
    out = []
    for row in values[1:]:
        padded = list(row) + [""] * (len(header) - len(row))
        record: dict[str, object] = {}
        for key, cell in zip(header, padded):
            if isinstance(cell, str):
                cell = cell.strip()
            if not record.get(key):
                record[key] = cell
        out.append(record)
    return out


def _require_header(tab: str, values: list[list[object]], header: str) -> None:
    """A hand-edited tab missing a whole column is a setup error, not a
    per-row problem: it can't be worked around, so it raises a clear
    ValueError naming the tab and the column, instead of the KeyError a
    later `row[header]` would otherwise raise."""
    if not values or header not in [_str(cell).strip().lower() for cell in values[0]]:
        raise ValueError(f"{tab} is missing the required '{header}' column")


def _serial_to_datetime(value: float) -> datetime:
    """Sheets serial day number -> naive datetime, rounded to the whole
    second. `claim_key` (sync/claims.py) embeds submitted_at, so any float
    wobble between two reads of the same cell would move page ids."""
    try:
        return EXCEL_EPOCH + timedelta(seconds=round(value * 86400))
    except OverflowError:
        raise ValueError(f"serial number out of range: {value!r}") from None


def _serial_to_date(value: float) -> date:
    """A date is the calendar day the serial falls in, so it is floored, not
    rounded (a timestamp rounds to the whole second instead, since claim
    keys depend on that, not on the calendar day)."""
    try:
        return (EXCEL_EPOCH + timedelta(days=math.floor(value))).date()
    except OverflowError:
        raise ValueError(f"serial number out of range: {value!r}") from None


def _timestamp(raw: object) -> datetime:
    if isinstance(raw, bool):
        raise ValueError(f"not a timestamp: {raw!r}")
    if isinstance(raw, (int, float)):
        return _serial_to_datetime(raw).replace(tzinfo=AMSTERDAM)
    return datetime.strptime(_str(raw).strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=AMSTERDAM)


def _date(raw: object) -> date:
    if isinstance(raw, bool):
        raise ValueError(f"not a date: {raw!r}")
    if isinstance(raw, (int, float)):
        return _serial_to_date(raw)
    return date.fromisoformat(_str(raw).strip())


def _safe_date(tab: str, row_num: int, raw: object, problems: list[str]) -> date | None:
    """A hand-edited tab's date column, guarded: a blank cell or a typed
    date such as '7 Oct' records a problem and drops the row rather than
    crashing the whole sync."""
    try:
        return _date(raw)
    except ValueError:
        problems.append(
            f"{tab} row {row_num} has date '{_str(raw)}', which is not a valid "
            "date (YYYY-MM-DD); skipping the row."
        )
        return None


def _label_to_code(raw: object, labels: dict[str, str]) -> str | None:
    """Map a form option back to its code, matching the visible label or the
    bare code, case-insensitively and ignoring surrounding whitespace. A form
    prefills the label (Google Forms needs the option's exact visible text);
    the rest of the system only ever sees the code."""
    value = _str(raw).strip().lower()
    if not value:
        return None
    if value in labels:
        return value
    for code, label in labels.items():
        if label.strip().lower() == value:
            return code
    return None


def _as_int(raw: object) -> int | None:
    """None if raw does not represent a whole number -- cleanly handling a
    Sheets cell that arrives as an int, a whole float (90.0), or text."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw) if raw.is_integer() else None
    try:
        return int(_str(raw).strip())
    except ValueError:
        return None


def _length_minutes(raw: object, row_num: int) -> tuple[int, str | None]:
    text = _str(raw).strip()
    if not text:
        return 60, None
    value = _as_int(raw)
    if value is None:
        problem = (
            f"Open sessions row {row_num} has length_minutes '{text}', which "
            "is not a whole number; using 60 instead."
        )
        return 60, problem
    return value, None


def _is_hidden(value: object, row_num: int, problems: list[str]) -> bool:
    """A Sheets checkbox column renders an unchecked box as the boolean or
    text FALSE, not blank, so a naive "any non-empty cell hides the row"
    check would hide every response the moment the hide column becomes
    checkboxes. An unrecognised value fails closed (hidden) with a problem,
    so an unexpected value never publishes silently."""
    if isinstance(value, bool):
        return value
    text = _str(value).strip().lower()
    if text in _HIDE_TRUE:
        return True
    if text in _HIDE_FALSE:
        return False
    problems.append(
        f"Responses row {row_num} has an unrecognised hide value '{value}'; "
        "hiding it to be safe."
    )
    return True


def _session_as_page_id(value: object) -> str:
    """A Session cell as page-id text. Google Forms may write a prefilled
    date, such as 2026-10-07, into a cell Sheets has auto-typed as a date, in
    which case it arrives as a serial number rather than a string."""
    if isinstance(value, bool):
        return _str(value)
    if isinstance(value, (int, float)):
        return _serial_to_date(value).isoformat()
    return _str(value)


def _valid_page_id(row: dict, row_num: int, problems: list[str]) -> str | None:
    raw_session = row.get("session", "")
    try:
        session_id = _session_as_page_id(raw_session)
    except ValueError:
        problems.append(
            f"Responses row {row_num} has an unreadable session "
            f"'{_str(raw_session)}'; skipping the row."
        )
        return None
    if not PAGE_ID_RE.fullmatch(session_id):
        problems.append(
            f"Responses row {row_num} has an unreadable session '{session_id}'; "
            "skipping the row."
        )
        return None
    return session_id


def read_all(reader: TabReader) -> SheetData:
    settings_values = reader.values("Settings")
    _require_header("Settings", settings_values, "key")
    _require_header("Settings", settings_values, "value")
    settings, problems = _settings(_rows(settings_values))
    data = SheetData(settings=settings, problems=problems)

    aliases_values = reader.values("Aliases")
    if aliases_values:
        _require_header("Aliases", aliases_values, "alias")
        _require_header("Aliases", aliases_values, "display name")
    aliases: dict[str, str] = {}
    for i, row in enumerate(_rows(aliases_values), start=2):
        alias = _str(row.get("alias", "")).strip()
        if not alias:
            continue
        display = _str(row.get("display name", "")).strip()
        if not display:
            data.problems.append(
                f"Aliases row {i} has alias '{alias}' with a blank display name; "
                "ignoring it."
            )
            continue
        aliases[alias.lower()] = display
    data.aliases = aliases

    for i, row in enumerate(_rows(reader.values("Skipped weeks")), start=2):
        day = _safe_date("Skipped weeks", i, row.get("date", ""), data.problems)
        if day is not None:
            data.skipped.add(day)

    for i, row in enumerate(_rows(reader.values("Open sessions")), start=2):
        day = _safe_date("Open sessions", i, row.get("date", ""), data.problems)
        if day is None:
            continue
        length_minutes, problem = _length_minutes(row.get("length_minutes", ""), i)
        if problem:
            data.problems.append(problem)
        data.open_sessions[day] = {
            "title": _str(row.get("title", "")) or None,
            "guest": _str(row.get("guest", "")) or None,
            "affiliation": _str(row.get("affiliation", "")) or None,
            "doi": normalise_doi(_opt_str(row, "doi")),
            "length_minutes": length_minutes,
        }

    for i, row in enumerate(_rows(reader.values("Session status")), start=2):
        day = _safe_date("Session status", i, row.get("date", ""), data.problems)
        if day is None:
            continue
        raw_status = _str(row.get("status", ""))
        status = raw_status.strip().lower()
        if status not in ("cancelled", "held"):
            data.problems.append(
                f"Session status row {i} has status '{raw_status}', which is "
                "neither 'cancelled' nor 'held'; ignoring it."
            )
            continue
        data.status[day] = status

    responses_values = reader.values("Responses")
    if not responses_values:
        data.problems.append(
            "The Responses tab is missing or has no header row; no submissions "
            "were read."
        )
    else:
        for i, row in enumerate(_rows(responses_values), start=2):
            if _is_hidden(row.get("hide", ""), i, data.problems):
                continue
            _read_response_row(row, i, aliases, data)

    return data


def _read_response_row(row: dict, row_num: int, aliases: dict[str, str], data: SheetData) -> None:
    raw_timestamp = row.get("timestamp", "")
    try:
        when = _timestamp(raw_timestamp)
    except ValueError:
        data.problems.append(
            f"Responses row {row_num} has an unreadable timestamp "
            f"'{_str(raw_timestamp)}'; skipping the row."
        )
        return

    raw_action = row.get("action", "")
    action = _label_to_code(raw_action, ACTION_LABELS)
    if action is None:
        data.problems.append(
            f"Responses row {row_num} has an unknown action '{_str(raw_action)}'; "
            "skipping the row."
        )
        return

    # The claim dict's name is never aliased: claim_key (sync/claims.py) is
    # keyed on it, so aliasing it here would move an already-assigned page
    # the moment an organiser added or fixed an alias. `aliases` is exposed
    # on SheetData for a later task to apply where a name is only displayed.
    raw_name = _str(row.get("name", ""))
    display_name = aliases.get(raw_name.lower(), raw_name)

    if action == "claim":
        if not raw_name:
            data.problems.append(f"Responses row {row_num} has an empty name; skipping the row.")
            return
        raw_session = row.get("session", "")
        try:
            day = _date(raw_session)
        except ValueError:
            data.problems.append(
                f"Responses row {row_num} has an unreadable session date "
                f"'{_str(raw_session)}'; skipping the row."
            )
            return
        raw_format = row.get("format", "")
        fmt = _label_to_code(raw_format, FORMAT_LABELS)
        if fmt is None:
            data.problems.append(
                f"Responses row {row_num} has an unknown format "
                f"'{_str(raw_format)}'; skipping the row."
            )
            return
        data.claims.append({
            "name": raw_name, "day": day, "fmt": fmt,
            "doi": normalise_doi(_opt_str(row, "doi")), "paper_title": _opt_str(row, "text"),
            "paper_link": _opt_str(row, "link"), "submitted_at": when, "hidden": False,
        })
    elif action == "takeaway":
        page_id = _valid_page_id(row, row_num, data.problems)
        if page_id is None:
            return
        if not display_name:
            data.problems.append(f"Responses row {row_num} has an empty name; skipping the row.")
            return
        takeaway_text = _str(row.get("takeaway", "")).strip()
        if not takeaway_text:
            data.problems.append(
                f"Responses row {row_num} has an empty takeaway; skipping the row."
            )
            return
        data.contributions.append(Contribution(
            page_id=page_id, part="takeaway", name=display_name,
            text=takeaway_text, link=None, submitted_at=when,
            approved=True, checked_by=None,
        ))
    elif action == "page":
        page_id = _valid_page_id(row, row_num, data.problems)
        if page_id is None:
            return
        if not display_name:
            data.problems.append(f"Responses row {row_num} has an empty name; skipping the row.")
            return
        raw_part = row.get("part", "")
        part = _label_to_code(raw_part, PART_LABELS)
        if part is None:
            data.problems.append(
                f"Responses row {row_num} has an unknown part '{_str(raw_part)}'; "
                "skipping the row."
            )
            return
        data.contributions.append(Contribution(
            page_id=page_id, part=part, name=display_name,
            text=_str(row.get("text", "")), link=_opt_str(row, "link"), submitted_at=when,
            approved=_str(row.get("status", "")).lower() == "approved",
            checked_by=_opt_str(row, "checked by"),
        ))
    elif action == "wishlist":
        if not display_name:
            data.problems.append(f"Responses row {row_num} has an empty name; skipping the row.")
            return
        data.wishlist.append(WishlistEntry(
            doi=normalise_doi(_opt_str(row, "doi")), paper_title=_opt_str(row, "text"),
            paper_link=_opt_str(row, "link"), name=display_name, why=_str(row.get("why", "")),
            submitted_at=when,
        ))
    elif action == "interest":
        doi = normalise_doi(_opt_str(row, "doi"))
        link = _str(row.get("link", ""))
        if not doi and not link:
            data.problems.append(
                f"Responses row {row_num} has neither a DOI nor a link; skipping the row."
            )
            return
        key = doi or link
        data.interest[key] = data.interest.get(key, 0) + 1


def _settings(rows: list[dict]) -> tuple[Settings, list[str]]:
    """A malformed Settings tab is the one fatal case: nothing downstream can
    run without it, so a missing key or an unparseable required value raises
    a ValueError naming the key rather than being recorded as a problem."""
    values = {row["key"]: row["value"] for row in rows if row.get("key")}
    problems: list[str] = []

    def require(key: str) -> object:
        if key not in values or values[key] in ("", None):
            raise ValueError(f"Settings is missing a value for '{key}'")
        return values[key]

    def require_int(key: str) -> int:
        raw = require(key)
        try:
            return int(_str(raw))
        except ValueError:
            raise ValueError(f"Settings key '{key}' must be a whole number, got '{raw}'") from None

    def require_date(key: str) -> date:
        raw = require(key)
        try:
            return _date(raw)
        except ValueError:
            raise ValueError(f"Settings key '{key}' must be a date (YYYY-MM-DD), got '{raw}'") from None

    first_session = require_date("first_session")
    if first_session.weekday() != WEDNESDAY:
        problems.append(
            f"Settings first_session '{first_session.isoformat()}' does not "
            "fall on a Wednesday; using it anyway."
        )

    settings = Settings(
        club_name=_str(require("club_name")),
        first_session=first_session,
        session_hour=require_int("session_hour"),
        session_minute=require_int("session_minute"),
        room=_str(require("room")),
        horizon_days=require_int("horizon_days"),
        site_base_url=_str(require("site_base_url")).rstrip("/"),
        form_url=_str(require("form_url")),
        entry_action=_str(require("entry_action")),
        entry_page=_str(require("entry_page")),
    )
    return settings, problems


class GspreadReader:
    """Read-only adapter. Not unit-tested; exercised by the smoke test in Task 14."""

    def __init__(self, sheet_id: str, credentials_json: str):
        client = gspread.service_account_from_dict(json.loads(credentials_json))
        self.sheet = client.open_by_key(sheet_id)

    def values(self, tab: str) -> list[list[object]]:
        # UNFORMATTED_VALUE + SERIAL_NUMBER keep dates and timestamps out of
        # the sheet's display locale: a Dutch-locale sheet would otherwise
        # format Timestamp as "17-9-2026 21:05:33" and every response row
        # would fail to parse. Both come back as Sheets serial day numbers
        # instead, which _timestamp/_date/_session_as_page_id convert.
        try:
            return self.sheet.worksheet(tab).get_all_values(
                value_render_option="UNFORMATTED_VALUE",
                date_time_render_option="SERIAL_NUMBER",
            )
        except gspread.WorksheetNotFound:
            return []
