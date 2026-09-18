import json
from datetime import datetime

from sync.archive import write_data
from sync.assemble import build_pages
from sync.claims import claim_key
from sync.config import AMSTERDAM
from sync.sheet import read_all
from tests.test_assemble import HEADER, row
from tests.test_sheet import data, reader

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=AMSTERDAM)


def read(root, name):
    return json.loads((root / "data" / name).read_text(encoding="utf-8"))


# -- R1: the claim-id map is persisted whole, never pruned -------------------

def test_a_retired_page_id_survives_the_round_trip_and_is_never_reissued(tmp_path):
    ann = row("2026-09-20 09:00:00", "claim", "2026-10-28", "Ann", fmt="full")
    first = read_all(reader(Responses=[HEADER, ann]))
    write_data(tmp_path, build_pages(first, {}, NOW), first, NOW)
    ann_key = claim_key(first.claims[0])
    assert read(tmp_path, "slots.json") == {ann_key: "2026-10-28"}

    # Ann's row is hidden, which releases the session, and Cy claims it.
    hidden = ann[:11] + ["yes"] + ann[12:]
    cy = row("2026-09-22 09:00:00", "claim", "2026-10-28", "Cy", fmt="full")
    second = read_all(reader(Responses=[HEADER, hidden, cy]))
    built = build_pages(second, read(tmp_path, "slots.json"), NOW)
    write_data(tmp_path, built, second, NOW)

    assert [s.page_id for s in built.slots] == ["2026-10-28-2"]
    slots = read(tmp_path, "slots.json")
    assert slots[ann_key] == "2026-10-28"
    assert slots[claim_key(second.claims[0])] == "2026-10-28-2"

    # And a third run on the persisted map still does not hand the bare id out.
    third = build_pages(second, read(tmp_path, "slots.json"), NOW)
    assert [s.page_id for s in third.slots] == ["2026-10-28-2"]


# -- R2: only publishable contributions enter the git archive -----------------

def test_an_unapproved_author_reply_never_enters_the_archive(tmp_path):
    rows = [HEADER,
            row("2026-10-08 09:00:00", "page", "2026-10-14", "Prof Real", part="reply",
                text="I am definitely the author"),
            row("2026-10-08 10:00:00", "page", "2026-10-14", "Prof Checked", part="reply",
                text="Thanks for reading it", status="approved")]
    rows[2][13] = "Max, by email"
    parsed = read_all(reader(Responses=rows))
    write_data(tmp_path, build_pages(parsed, {}, NOW), parsed, NOW)

    names = [c["name"] for c in read(tmp_path, "submissions.json")]
    assert names == ["Prof Checked"]


def test_an_unapproved_synthesis_never_enters_the_archive(tmp_path):
    rows = [HEADER,
            row("2026-10-08 09:00:00", "page", "2026-10-14", "Ann", part="synthesis",
                text="Not yet agreed with the presenter")]
    parsed = read_all(reader(Responses=rows))
    write_data(tmp_path, build_pages(parsed, {}, NOW), parsed, NOW)
    assert read(tmp_path, "submissions.json") == []


def test_publishable_contributions_enter_the_archive_only_after_seven_days(tmp_path):
    parsed = data()
    late = datetime(2026, 10, 25, 12, 0, tzinfo=AMSTERDAM)
    write_data(tmp_path, build_pages(parsed, {}, late), parsed, late)
    archived = read(tmp_path, "submissions.json")
    assert sorted(c["part"] for c in archived) == ["synthesis", "takeaway"]

    # Seven days after the takeaway (14 Oct 12:10), not after the synthesis (15 Oct 09:00).
    early = datetime(2026, 10, 21, 13, 0, tzinfo=AMSTERDAM)
    write_data(tmp_path, build_pages(parsed, {}, early), parsed, early)
    assert [c["part"] for c in read(tmp_path, "submissions.json")] == ["takeaway"]


# -- the other files ----------------------------------------------------------

def test_the_schedule_and_sync_state_are_written(tmp_path):
    parsed = data()
    write_data(tmp_path, build_pages(parsed, {}, NOW), parsed, NOW)
    schedule = read(tmp_path, "schedule.json")
    assert schedule[0] == {"day": "2026-09-30", "kind": "regular", "status": "unrecorded",
                           "title": None, "guest": None, "length_minutes": 60}
    assert read(tmp_path, "sync_state.json") == {"last_run": NOW.isoformat(),
                                                   "keepalive_month": "2026-10"}
