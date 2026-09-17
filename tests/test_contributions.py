from datetime import datetime, timedelta

from sync.config import AMSTERDAM
from sync.contributions import archivable, attach, pending, publishable
from sync.model import Contribution, Page, Session
from datetime import date

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=AMSTERDAM)


def contribution(part, name="Ann", approved=False, checked_by=None, when=NOW, text="t"):
    return Contribution(
        page_id="2026-10-07", part=part, name=name, text=text, link=None,
        submitted_at=when, approved=approved, checked_by=checked_by,
    )


def test_appended_parts_publish_without_approval():
    rows = [contribution("takeaway"), contribution("next")]
    assert publishable(rows) == rows


def test_presenter_content_waits_for_approval():
    unapproved = contribution("synthesis")
    approved = contribution("connections", approved=True)
    assert publishable([unapproved, approved]) == [approved]
    assert pending([unapproved, approved]) == [unapproved]


def test_an_author_reply_needs_an_identity_check_as_well_as_approval():
    approved_only = contribution("reply", approved=True)
    checked = contribution("reply", approved=True, checked_by="Max")
    assert publishable([approved_only, checked]) == [checked]


def test_replaced_parts_keep_only_the_newest_submission():
    old = contribution("synthesis", approved=True, when=NOW - timedelta(days=2), text="old")
    new = contribution("synthesis", approved=True, when=NOW, text="new")
    pages = {"2026-10-07": Page(page_id="2026-10-07",
                                session=Session(day=date(2026, 10, 7), kind="regular", status="held"),
                                slot=None)}
    attach(pages, [old, new])
    assert pages["2026-10-07"].synthesis.text == "new"


def test_appended_parts_accumulate_in_submission_order():
    first = contribution("takeaway", when=NOW - timedelta(days=1), text="first")
    second = contribution("takeaway", when=NOW, text="second")
    pages = {"2026-10-07": Page(page_id="2026-10-07",
                                session=Session(day=date(2026, 10, 7), kind="regular", status="held"),
                                slot=None)}
    attach(pages, [second, first])
    assert [t.text for t in pages["2026-10-07"].takeaways] == ["first", "second"]


def test_only_contributions_older_than_seven_days_are_archivable():
    fresh = contribution("takeaway", when=NOW - timedelta(days=6))
    old = contribution("takeaway", when=NOW - timedelta(days=8))
    assert archivable([fresh, old], NOW) == [old]
