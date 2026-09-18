"""Turn sheet data into pages. A page exists for every session; only sessions
with evidence are marked held. A takeaway is evidence only once its session
has started: an early one still attaches to its page, but the session stays
scheduled, so it is never both upcoming and in the library.

An unclaimed session's page takes the first id in the long sequence (the
date, then date-2, ...) that no claim has ever held. A released claim's id is
retired, so the open chat that replaces it never inherits its takeaways.

Names are aliased here for display only, after resolve_claims has fixed every
page id. The claim key embeds the claimant's name as submitted, so aliasing
before that point would move a page the moment someone added an alias.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime

from sync.claims import Rejection, next_id, resolve_claims
from sync.config import session_start
from sync.contributions import attach, pending
from sync.model import Contribution, Page, Session, Slot
from sync.schedule import generate_sessions, off_grid
from sync.sheet import SheetData

# How a contribution is named in a problem report.
PART_NAMES = {
    "takeaway": "Takeaway",
    "synthesis": "Discussion synthesis",
    "connections": "Note on what it means for our work",
    "slides": "Slides link",
    "explainer": "Explainer link",
    "next": "Follow-up",
    "reply": "Author reply",
}


@dataclass
class Built:
    pages: dict[str, Page] = field(default_factory=dict)
    sessions: list[Session] = field(default_factory=list)
    slots: list[Slot] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    assigned: dict[str, str] = field(default_factory=dict)
    refused: set[str] = field(default_factory=set)
    pending: list[Contribution] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def build_pages(data: SheetData, assigned: dict[str, str], now: datetime,
                refused: set[str] = frozenset()) -> Built:
    """`assigned` is the whole claim-key -> page-id map from data/slots.json,
    and `refused` the whole set of refused claim keys from data/refused.json.
    The returned `built.assigned` and `built.refused` are those plus this
    run's additions, and must be persisted whole: see write_data."""
    sessions = generate_sessions(
        data.settings, data.skipped, data.open_sessions, data.status, now.date()
    )
    starts = {s.day: session_start(s.day, data.settings) for s in sessions}
    claims = resolve_claims(sessions, data.claims, assigned, refused, starts)
    built = Built(
        sessions=sessions,
        slots=[replace(s, presenter=_display(s.presenter, data.aliases)) for s in claims.slots],
        rejections=[replace(r, name=_display(r.name, data.aliases)) for r in claims.rejections],
        assigned=claims.assigned,
        refused=claims.refused,
        pending=pending(data.contributions),
    )

    slots_by_day: dict = {}
    for slot in built.slots:
        slots_by_day.setdefault(slot.day, []).append(slot)

    retired = set(built.assigned.values())
    for session in sessions:
        for slot in slots_by_day.get(session.day, []) or [None]:
            page_id = slot.page_id if slot else next_id(session.day.isoformat(), "full", retired)
            built.pages[page_id] = Page(page_id=page_id, session=session, slot=slot)

    attach(built.pages, data.contributions)
    built.problems = [
        f"{PART_NAMES[row.part]} from {row.name} names page {row.page_id}, which does not exist"
        for row in sorted(data.contributions, key=lambda r: r.submitted_at)
        if row.page_id not in built.pages
    ]
    for tab, days in (("Skipped weeks", data.skipped), ("Session status", data.status),
                      ("Open sessions", data.open_sessions)):
        built.problems += [
            f"{tab} lists {day.isoformat()}, which is not a session date: sessions fall "
            f"every other Wednesday from {data.settings.first_session.isoformat()}. "
            "The row has no effect."
            for day in off_grid(days, data.settings, now.date())
        ]

    # Held is a session's status (spec 4.4), so a takeaway on one short slot
    # marks every page of that session held, and the schedule says so too.
    held_days = {
        page.session.day for page in built.pages.values()
        if page.takeaways and page.session.status not in ("cancelled", "held")
        and now >= starts[page.session.day]
    }
    for page in built.pages.values():
        if page.session.day in held_days:
            page.session = replace(page.session, status="held")
    built.sessions = [replace(s, status="held") if s.day in held_days else s for s in sessions]
    return built


def _display(name: str, aliases: dict[str, str]) -> str:
    return aliases.get(name.lower(), name)
