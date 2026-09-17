"""Dataclasses shared across the sync package."""

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class Session:
    day: date
    kind: str            # "regular" or "open"
    status: str          # "scheduled", "held", "cancelled", "unrecorded"
    title: str | None = None
    guest: str | None = None
    length_minutes: int = 60


@dataclass(frozen=True)
class Slot:
    page_id: str         # "2026-10-07" or "2026-10-07-a"
    day: date
    presenter: str
    fmt: str             # "help", "full", "short"
    doi: str | None
    paper_title: str | None
    paper_link: str | None
    claimed_at: datetime


@dataclass(frozen=True)
class Contribution:
    page_id: str
    part: str            # see PARTS below
    name: str
    text: str
    link: str | None
    submitted_at: datetime
    approved: bool
    checked_by: str | None


@dataclass(frozen=True)
class WishlistEntry:
    doi: str | None
    paper_title: str | None
    paper_link: str | None
    name: str
    why: str
    submitted_at: datetime
    interest: int = 0


@dataclass
class Page:
    page_id: str
    session: Session
    slot: Slot | None
    takeaways: list[Contribution] = field(default_factory=list)
    follow_ups: list[Contribution] = field(default_factory=list)
    replies: list[Contribution] = field(default_factory=list)
    synthesis: Contribution | None = None
    connections: Contribution | None = None
    slides: Contribution | None = None
    explainer: Contribution | None = None


APPENDED_PARTS = ("takeaway", "next", "reply")
REPLACED_PARTS = ("synthesis", "connections", "slides", "explainer")
PARTS = APPENDED_PARTS + REPLACED_PARTS
