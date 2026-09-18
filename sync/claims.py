"""Resolve claim rows into slots. Page ids are assigned once and never reused,
and a claim is refused at most once.

Three records reach this module from earlier runs, and together they make
resolution depend only on the sheet and on what earlier runs decided, never on
the clock, so sync, build and announce always agree:

- `assigned` maps the key of every claim ever placed to its page id. Those ids
  are retired forever, even once the claim row is gone (released or hidden),
  so a later claimant on the same session gets the next free id instead of
  reusing a page whose takeaways belong to someone else.
- `refused` holds the key of every claim ever refused. Its claimant was told
  it was not placed, and may have claimed another session since, so it is
  never placed later: not when the session is released, nor when its date
  comes into range, nor when a skip or a cancellation is lifted.
- `starts` gives each session's start. A claim made at or after its
  session's start is refused, judged by when it was submitted rather than by
  when a run first saw it: a claim made in good time still counts after an
  outage, and one made during a same-day open chat cannot take the chat's page.

Resolution runs in two passes. Claims placed in an earlier run go first and
keep their ids and their places, on any regular session, a cancelled one
included, so an older row that only now becomes readable (fixed after a
problem report, or unhidden before it was ever placed) can never bump a claim
that was already confirmed. New claims then fill what is left, earliest
first. Capacity counts only the claims placed in this run: a session holds
either one long slot (fmt "full" or "help") or up to two short slots.
"""

import itertools
import string
from dataclasses import dataclass, field
from datetime import date, datetime

from sync.model import Session, Slot

LONG_FORMATS = ("full", "help")


@dataclass(frozen=True)
class Rejection:
    name: str
    day: date | None
    reason: str          # "taken", "not-claimable"
    key: str             # claim_key of the rejected row, which logs its notice


@dataclass
class ClaimResult:
    slots: list[Slot] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    assigned: dict[str, str] = field(default_factory=dict)
    refused: set[str] = field(default_factory=set)


def claim_key(row: dict) -> str:
    return row["submitted_at"].isoformat() + "|" + row["name"]


def resolve_claims(sessions: list[Session], rows: list[dict], assigned: dict[str, str],
                   refused: set[str], starts: dict[date, datetime]) -> ClaimResult:
    regular = {s.day: s for s in sessions if s.kind == "regular"}
    result = ClaimResult(assigned=dict(assigned), refused=set(refused))
    taken_ids = set(result.assigned.values())
    live_formats: dict[date, list[str]] = {}

    # One claim per key, earliest row first: a repeated row is not a second claim.
    claims: dict[str, dict] = {}
    for row in sorted(rows, key=lambda r: r["submitted_at"]):
        if not row["hidden"]:
            claims.setdefault(claim_key(row), row)

    def place(row: dict, page_id: str) -> None:
        live_formats.setdefault(row["day"], []).append(row["fmt"])
        result.slots.append(
            Slot(
                page_id=page_id,
                day=row["day"],
                presenter=row["name"],
                fmt=row["fmt"],
                doi=row["doi"],
                paper_title=row["paper_title"],
                paper_link=row["paper_link"],
                claimed_at=row["submitted_at"],
            )
        )

    # Pass 1: claims placed in an earlier run. One whose date has become a
    # skipped week or an open session has no session to hang a page on, and
    # one that no longer fits was overfilled by a hand edit; both are left
    # off the site without a notice, and keep their ids.
    for key, row in claims.items():
        page_id = result.assigned.get(key)
        if page_id is None or row["day"] not in regular:
            continue
        if _fits(row["fmt"], live_formats.get(row["day"], [])):
            place(row, page_id)

    # Pass 2: new claims, earliest first. A claim refused before was already
    # told so, once; it gets neither a slot nor a second notice.
    for key, row in claims.items():
        if key in result.assigned or key in result.refused:
            continue
        session = regular.get(row["day"])
        if (session is None or session.status == "cancelled"
                or row["submitted_at"] >= starts[row["day"]]):
            reason = "not-claimable"
        elif not _fits(row["fmt"], live_formats.get(row["day"], [])):
            reason = "taken"
        else:
            page_id = _next_id(row["day"].isoformat(), row["fmt"], taken_ids)
            result.assigned[key] = page_id
            taken_ids.add(page_id)
            place(row, page_id)
            continue
        result.rejections.append(Rejection(row["name"], row["day"], reason, key))
        result.refused.add(key)

    result.slots.sort(key=lambda s: s.page_id)
    return result


def _fits(fmt: str, existing: list[str]) -> bool:
    """Can a claim of this format still be placed given the live claims so far?"""
    if not existing:
        return True
    if any(f in LONG_FORMATS for f in existing):
        return False  # a long slot already fills the whole session
    if fmt in LONG_FORMATS:
        return False  # shorts already started; no room for a long slot
    return len(existing) < 2


def _next_id(day: str, fmt: str, taken_ids: set[str]) -> str:
    if fmt in LONG_FORMATS:
        candidates = itertools.chain([day], (f"{day}-{n}" for n in itertools.count(2)))
    else:
        candidates = (f"{day}-{suffix}" for suffix in _short_suffixes())
    for candidate in candidates:
        if candidate not in taken_ids:
            return candidate
    raise AssertionError("unreachable: candidate sequence is infinite")


def _short_suffixes():
    """a, b, ..., z, aa, ab, ... -- an inexhaustible sequence of short-slot suffixes."""
    for length in itertools.count(1):
        for combo in itertools.product(string.ascii_lowercase, repeat=length):
            yield "".join(combo)
