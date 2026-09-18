"""When to announce, and what to say. The log guarantees no message is posted
twice; it cannot guarantee that every message is posted."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sync.config import AMSTERDAM, Settings, session_start
from sync.mattermost import neutral
from sync.model import Session, Slot

WINDOWS = {"friday": (-5, 9), "monday": (-2, 9), "wednesday": (0, 8)}


@dataclass(frozen=True)
class Announcement:
    key: str
    kind: str
    day: date
    text: str


def _opened_windows(now: datetime, session: Session, claimed: list[Slot], settings: Settings) -> list[tuple[str, datetime]]:
    """Return opened and applicable windows as (kind, opens) tuples, sorted by opening time."""
    opened = []
    for kind, (offset, hour) in WINDOWS.items():
        if kind == "friday" and (claimed or session.kind == "open"):
            continue
        opens = datetime(
            *(session.day + timedelta(days=offset)).timetuple()[:3],
            hour, 0, tzinfo=session_start(session.day, settings).tzinfo,
        )
        if now >= opens:
            opened.append((kind, opens))
    # Sort by opening time (ascending)
    opened.sort(key=lambda x: x[1])
    return opened


def due(now: datetime, sessions, slots, log: dict, settings: Settings) -> list[Announcement]:
    by_day: dict[date, list[Slot]] = {}
    for slot in slots:
        by_day.setdefault(slot.day, []).append(slot)

    found: list[Announcement] = []
    for session in sessions:
        if session.status == "cancelled":
            continue
        if now >= session_start(session.day, settings):
            continue
        claimed = by_day.get(session.day, [])

        opened = _opened_windows(now, session, claimed, settings)
        if opened:
            latest_kind = opened[-1][0]  # Last (latest) opened window
            key = f"{session.day.isoformat()}:{latest_kind}"
            if key not in log:
                found.append(Announcement(key, latest_kind, session.day, _text(latest_kind, session, claimed, settings)))
    return found


def _text(kind: str, session: Session, claimed: list[Slot], settings: Settings) -> str:
    when = f"{session.day.day} {session.day.strftime('%B')}"
    where = f"{when} {settings.session_hour:02d}:{settings.session_minute:02d}, {settings.room}"
    if kind == "friday":
        return (f"No one has claimed {when} yet, so it is an open paper chat: "
                f"bring anything you read, no slides. {where}. Claim it instead: "
                f"{settings.site_base_url}/")
    if session.kind == "open":
        # A guest session is never claimed, but it is not an open paper chat.
        # Its title and guest come from a tab every lab member can edit.
        body = neutral(session.title or "Open session")
        if session.guest:
            body += f", with {neutral(session.guest)}"
        body += ". Open to people outside the lab."
        if session.length_minutes != 60:
            body += f" {session.length_minutes} minutes."
    elif not claimed:
        body = "Open paper chat: bring anything you read, no slides."
    else:
        body = " ".join(
            f"{neutral(slot.presenter)} on {neutral(slot.paper_title or slot.doi or 'a paper')} "
            f"({_format_name(slot.fmt)}): {settings.site_base_url}/sessions/{slot.page_id}/"
            for slot in claimed
        )
    prefix = "This Wednesday" if kind == "monday" else "Today"
    return f"{prefix}, {where}. {body}"


def _format_name(fmt: str) -> str:
    return {"help": "help me read this", "full": "presentation", "short": "one figure"}[fmt]


def mark_sending(log: dict, announcement: Announcement) -> None:
    log[announcement.key] = {"state": "sending", "at": datetime.now(AMSTERDAM).isoformat()}


def mark_sent(log: dict, announcement: Announcement) -> None:
    log[announcement.key] = {"state": "sent", "at": datetime.now(AMSTERDAM).isoformat()}


def mark_skipped(log: dict, key: str) -> None:
    log[key] = {"state": "skipped", "at": datetime.now(AMSTERDAM).isoformat()}


def claim_announcements(now: datetime, sessions, slots, log: dict, settings: Settings) -> list[Announcement]:
    # A claim placed before its session was cancelled keeps its page, but is
    # never confirmed for a session that will not happen.
    cancelled = {session.day for session in sessions if session.status == "cancelled"}
    found = []
    for slot in slots:
        # Skip if session has already started
        if now >= session_start(slot.day, settings) or slot.day in cancelled:
            continue
        key = f"{slot.page_id}:claim"
        if key in log:
            continue
        day_str = f"{slot.day.day} {slot.day.strftime('%B')}"
        found.append(Announcement(
            key, "claim", slot.day,
            f"{neutral(slot.presenter)} claimed {slot.day.strftime('%A')} {day_str} "
            f"({_format_name(slot.fmt)}): {settings.site_base_url}/sessions/{slot.page_id}/",
        ))
    return found


def superseded(now: datetime, sessions, slots, log: dict, settings: Settings) -> list[str]:
    """Return keys of windows that have opened and apply but are not the latest and are not yet logged."""
    by_day: dict[date, list[Slot]] = {}
    for slot in slots:
        by_day.setdefault(slot.day, []).append(slot)

    skipped = []
    for session in sessions:
        if session.status == "cancelled":
            continue
        if now >= session_start(session.day, settings):
            continue
        claimed = by_day.get(session.day, [])

        opened = _opened_windows(now, session, claimed, settings)
        if len(opened) > 1:
            # All windows except the latest are superseded
            for kind, _ in opened[:-1]:
                key = f"{session.day.isoformat()}:{kind}"
                if key not in log:
                    skipped.append(key)

    return skipped
