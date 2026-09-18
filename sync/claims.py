"""Resolve claim rows into slots. Page ids are assigned once and never reused.

Capacity (can this row be placed?) and id uniqueness (which id does it get?)
are tracked separately:

- Capacity is about live slots placed DURING THIS RUN only. A session holds
  either one long slot (fmt "full" or "help") or up to two short slots.
- Id uniqueness is about every id that has ever been handed out. Any id
  present in the `assigned` map passed in is retired forever, even once its
  claim row is gone (released or hidden), so a later claimant on the same
  session gets the next free id instead of reusing a page whose takeaways
  belong to someone else.
"""

import itertools
import string
from dataclasses import dataclass, field
from datetime import date

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


def claim_key(row: dict) -> str:
    return row["submitted_at"].isoformat() + "|" + row["name"]


def resolve_claims(sessions: list[Session], rows: list[dict], assigned: dict[str, str]) -> ClaimResult:
    claimable = {s.day for s in sessions if s.kind == "regular" and s.status != "cancelled"}
    result = ClaimResult(assigned=dict(assigned))
    taken_ids = set(result.assigned.values())
    live_formats: dict[date, list[str]] = {}

    for row in sorted(rows, key=lambda r: r["submitted_at"]):
        if row["hidden"]:
            continue
        if row["day"] not in claimable:
            result.rejections.append(
                Rejection(row["name"], row["day"], "not-claimable", claim_key(row))
            )
            continue

        existing = live_formats.get(row["day"], [])
        if not _fits(row["fmt"], existing):
            result.rejections.append(Rejection(row["name"], row["day"], "taken", claim_key(row)))
            continue

        key = claim_key(row)
        page_id = result.assigned.get(key)
        if page_id is None:
            page_id = _next_id(row["day"].isoformat(), row["fmt"], taken_ids)
            result.assigned[key] = page_id
            taken_ids.add(page_id)

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
