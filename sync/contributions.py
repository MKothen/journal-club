"""Publication rules. An open form must not mean open overwrite authority."""

from datetime import datetime, timedelta

from sync.config import ARCHIVE_DELAY_DAYS
from sync.model import APPENDED_PARTS, REPLACED_PARTS, Contribution, Page

_APPEND_FIELD = {"takeaway": "takeaways", "next": "follow_ups", "reply": "replies"}


def _is_publishable(row: Contribution) -> bool:
    if row.part in REPLACED_PARTS:
        return row.approved
    if row.part == "reply":
        return row.approved and bool(row.checked_by)
    return row.part in APPENDED_PARTS


def publishable(rows: list[Contribution]) -> list[Contribution]:
    return [r for r in rows if _is_publishable(r)]


def pending(rows: list[Contribution]) -> list[Contribution]:
    return [r for r in rows if not _is_publishable(r)]


def attach(pages: dict[str, Page], rows: list[Contribution]) -> None:
    for row in sorted(publishable(rows), key=lambda r: r.submitted_at):
        page = pages.get(row.page_id)
        if page is None:
            continue
        if row.part in REPLACED_PARTS:
            setattr(page, row.part, row)
        else:
            getattr(page, _APPEND_FIELD[row.part]).append(row)


def archivable(rows: list[Contribution], now: datetime) -> list[Contribution]:
    cutoff = now - timedelta(days=ARCHIVE_DELAY_DAYS)
    return [r for r in rows if r.submitted_at <= cutoff]
