"""Command line entry points used by the workflow.

    python -m sync.cli sync      read the sheet, write data, copy explainers
    python -m sync.cli build     render the site into _site/
    python -m sync.cli announce  post anything due to Mattermost

Every external effect -- the sheet, the clock, git, Mattermost, doi.org and
the explainer hosts -- reaches a command through an Effects bundle, so the
tests run offline and never run git.

No message is posted twice, and that includes sync's own notices. Every post
goes through the announcement log, data/announcements.json: its keys are
written as "sending" and persisted to git BEFORE the post, then marked "sent".
A run that dies after posting has already put "sending" into git, and a key
already in the log is never posted again. If persisting fails, the message is
not posted at all: at most once is the promise, not exactly once. The claim
records, data/slots.json and data/refused.json, are persisted with the log,
so a "not placed" notice never goes out while its refusal is still unrecorded.
"""

import hashlib
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sync.announce import (
    Announcement,
    claim_announcements,
    due,
    mark_sending,
    mark_sent,
    mark_skipped,
    superseded,
)
from sync.archive import read_json, write_data, write_json
from sync.assemble import PART_NAMES, Built, build_pages
from sync.config import AMSTERDAM, Settings, session_start
from sync.explainers import ExplainerError, fetch_explainer, http_get_text, store_explainer
from sync.mattermost import neutral, post
from sync.model import Contribution, Page
from sync.papers import http_fetch, paper_metadata
from sync.sheet import GspreadReader, SheetData, TabReader, read_all

ROOT = Path(__file__).resolve().parent.parent
LOG = "data/announcements.json"
CLAIM_RECORDS = ("data/slots.json", "data/refused.json")

REJECTION_REASONS = {
    "taken": "that session is already taken",
    "not-claimable": "that date is not an open session that can be claimed",
}


@dataclass(frozen=True)
class Effects:
    reader: TabReader
    now: datetime
    persist: Callable[[], None]           # commit and push the announcement log
    send: Callable[[str], object]         # post one message to Mattermost
    get_explainer: Callable[[str], str]   # download one explainer link as text
    get_doi: Callable[[str, dict], dict]  # fetch CSL JSON from one doi.org URL


def production_effects() -> Effects:
    webhook = os.environ.get("MATTERMOST_WEBHOOK_URL")
    return Effects(
        reader=GspreadReader(os.environ["SHEET_ID"], os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]),
        now=datetime.now(AMSTERDAM),
        persist=lambda: git_persist(ROOT),
        # Without a webhook, post() prints the text for pasting by hand.
        send=lambda text: post(text, webhook),
        get_explainer=http_get_text,
        get_doi=http_fetch,
    )


def git_persist(root: Path, run=subprocess.run) -> None:
    """Commit and push the announcement log, with the claim records that
    exist: a refusal must reach git no later than its "not placed" notice,
    and the archive commit that follows the sync step may never happen. A
    missing record is left out, since `git add` of a missing path fails.
    Nothing else is committed here. There is no safe.directory override: the
    runner owns its checkout. With nothing to commit the push still runs, so
    an earlier commit whose push failed goes out now, and a push with nothing
    new succeeds silently."""
    paths = [LOG] + [path for path in CLAIM_RECORDS if (root / path).exists()]
    run(["git", "add", *paths], cwd=root, check=True)
    staged = run(["git", "diff", "--cached", "--quiet", "--", *paths], cwd=root)
    if staged.returncode not in (0, 1):
        raise subprocess.CalledProcessError(staged.returncode, staged.args)
    if staged.returncode == 1:
        run(["git", "commit", "-m", "chore: announcement log", "--", *paths], cwd=root, check=True)
    run(["git", "push"], cwd=root, check=True)


# -- posting at most once --------------------------------------------------------

class PersistFailed(Exception):
    """The announcement log could not be persisted, so nothing more was posted."""


@dataclass(frozen=True)
class Message:
    """One Mattermost post and the log entries that guard it. A digest is one
    post guarded by several entries, one per line it reports."""
    guards: tuple[Announcement, ...]
    text: str


def deliver(messages: list[Message], log: dict, log_path: Path,
            persist: Callable[[], None], send: Callable[[str], object]) -> int:
    """Post each message at most once, in order. Returns how many posts
    raised: those stay "sending" and are never retried, because the message
    may have gone out anyway. Raises PersistFailed, having posted nothing
    more, when the log cannot be persisted.

    The log is persisted once more at the end only if it gained something
    that is not on disk yet ("sent" marks, or skipped windows marked by the
    caller). A run with nothing to record never touches git, so a network
    blip on a pointless push cannot fail it."""
    failed = 0
    for message in messages:
        if any(guard.key in log for guard in message.guards):
            continue  # already posted or attempted, possibly earlier in this run
        for guard in message.guards:
            mark_sending(log, guard)
        write_json(log_path, log)
        try:
            persist()
        except Exception as error:
            # Nothing was posted, so these entries guard nothing. Removing
            # them lets a later run post the message, still at most once.
            for guard in message.guards:
                log.pop(guard.key, None)
            write_json(log_path, log)
            raise PersistFailed(f"Announcement log not persisted, so not posted: {error}") from error
        try:
            send(message.text)
        except Exception as error:
            print(f"Mattermost post failed ({_describe(error)}); "
                  "it stays 'sending' and is not retried.")
            failed += 1
            continue
        for guard in message.guards:
            mark_sent(log, guard)
    if log != read_json(log_path, {}):
        write_json(log_path, log)
        try:
            persist()
        except Exception as error:
            raise PersistFailed(f"Announcement log not persisted after posting: {error}") from error
    return failed


# -- the commands ------------------------------------------------------------------

def _load(root: Path, fx: Effects) -> tuple[SheetData, Built]:
    data = read_all(fx.reader)
    assigned = read_json(root / "data" / "slots.json", {})
    refused = set(read_json(root / "data" / "refused.json", []))
    return data, build_pages(data, assigned, fx.now, refused)


def cmd_sync(root: Path = ROOT, fx: Effects | None = None) -> int:
    if fx is None:
        fx = production_effects()
    data, built = _load(root, fx)
    # Written first, so no failure later in the run can leave a page id that
    # announce is about to link to unrecorded.
    write_data(root, built, data, fx.now)
    _look_up_papers(root, built, data, fx)
    failures = _copy_explainers(root, built, fx)

    log_path = root / LOG
    log = read_json(log_path, {})
    # A failed post does not fail this step, so a Mattermost outage never
    # costs the site its archive commit and its build. It is handed to the
    # workflow instead, whose "Fail if a notice was not posted" step turns
    # the run red after the announcements. A failed persist does fail the
    # step: git itself is broken, and the archive commit would fail too.
    try:
        failed = deliver(_notices(built, data, failures, log, fx.now),
                         log, log_path, fx.persist, fx.send)
    except PersistFailed as error:
        print(error)
        return 1
    if failed:
        _report_failed_notices(failed)
    return 0


def _report_failed_notices(failed: int) -> None:
    """An error annotation on the run, and notices_failed=N as a step output
    when the workflow provides a place for one."""
    print(f"::error::{failed} notice(s) could not be posted to Mattermost; "
          "see the sending entries in data/announcements.json")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"notices_failed={failed}\n")


def cmd_build(root: Path = ROOT, fx: Effects | None = None,
              render: Callable[[Path, Built, SheetData], None] | None = None) -> int:
    if fx is None:
        fx = production_effects()
    if render is None:
        from web.build import render  # the site (Task 11); sync and announce never need it
    data, built = _load(root, fx)
    render(root, built, data)
    return 0


def cmd_announce(root: Path = ROOT, fx: Effects | None = None) -> int:
    if fx is None:
        fx = production_effects()
    data, built = _load(root, fx)
    log_path = root / LOG
    log = read_json(log_path, {})
    for key in superseded(fx.now, built.sessions, built.slots, log, data.settings):
        mark_skipped(log, key)
    found = (claim_announcements(fx.now, built.sessions, built.slots, log, data.settings)
             + due(fx.now, built.sessions, built.slots, log, data.settings))
    try:
        failed = deliver([Message((item,), item.text) for item in found],
                         log, log_path, fx.persist, fx.send)
    except PersistFailed as error:
        print(error)
        return 1
    return 1 if failed else 0


# -- sync's steps ------------------------------------------------------------------

def _look_up_papers(root: Path, built: Built, data: SheetData, fx: Effects) -> None:
    """Every claimed slot's DOI, and every open session's, so a guest page
    shows its paper's title and authors too."""
    path = root / "data" / "papers" / "cache.json"
    cache = read_json(path, {})
    dois = {slot.doi for slot in built.slots if slot.doi}
    dois |= {spec["doi"] for spec in data.open_sessions.values() if spec.get("doi")}
    for doi in sorted(dois):
        try:
            paper_metadata(doi, cache, fetch=fx.get_doi)
        except Exception as error:
            # The page shows the DOI or title as given, and the next run retries.
            print(f"DOI lookup failed for {doi}, retrying next run: {error}")
    write_json(path, cache)


def _copy_explainers(root: Path, built: Built, fx: Effects) -> list[tuple[Page, str, ExplainerError]]:
    """Fetch an approved explainer only when its link differs from the one
    last fetched for that page, or its stored copy is gone. A failed fetch is
    not recorded, so it is retried every run: the usual fix, a presenter
    changing the file's sharing setting, leaves the link unchanged."""
    path = root / "data" / "explainers.json"
    fetched = read_json(path, {})
    failures = []
    for page in built.pages.values():
        link = page.explainer.link if page.explainer else None
        if not link:
            continue
        stored = root / "explainers" / page.page_id / "explainer.txt"
        if fetched.get(page.page_id) == link and stored.exists():
            continue
        try:
            store_explainer(root, page.page_id, fetch_explainer(link, fetch=fx.get_explainer))
        except ExplainerError as error:
            failures.append((page, link, error))
            continue
        fetched[page.page_id] = link
    write_json(path, fetched)
    return failures


def _notices(built: Built, data: SheetData, failures, log: dict, now: datetime) -> list[Message]:
    settings = data.settings
    messages = [_rejection(r, built, settings, now) for r in built.rejections]
    messages += [_explainer_failure(page, link, error) for page, link, error in failures]
    if built.pending:
        messages.append(_pending(built.pending, now))
    digest = _problem_digest(data.problems + built.problems, log, now)
    if digest:
        messages.append(digest)
    return messages


def _rejection(rejection, built: Built, settings: Settings, now: datetime) -> Message:
    when = f" for {_day(rejection.day)}" if rejection.day else ""
    reason = REJECTION_REASONS.get(rejection.reason, rejection.reason)
    text = (f"{neutral(rejection.name)}: your claim{when} was not placed, because {reason}. "
            f"{_next_open(built, settings, now)}")
    return _single(f"reject:{rejection.key}", "reject", rejection.day or now.date(), text)


def _next_open(built: Built, settings: Settings, now: datetime) -> str:
    """Links the unclaimed session's own page, whose id is not always the
    bare date: a released claim retires that one."""
    claimed = {slot.day for slot in built.slots}
    unclaimed = {page.session.day: page.page_id for page in built.pages.values() if page.slot is None}
    for session in built.sessions:
        if (session.kind == "regular" and session.status == "scheduled"
                and session.day not in claimed
                and session_start(session.day, settings) > now):
            return (f"The next open session is {_day(session.day)}: "
                    f"{settings.site_base_url}/sessions/{unclaimed[session.day]}/")
    return "There is no open session in the schedule yet."


def _explainer_failure(page: Page, link: str, error: ExplainerError) -> Message:
    # The error can quote part of the submitted link, which came from the form.
    text = f"The explainer for page {page.page_id} was not published: {neutral(str(error))}"
    return _single(f"explainer-failed:{page.page_id}:{_sha1(link)}",
                   "explainer-failed", page.session.day, text)


def _pending(rows: list[Contribution], now: datetime) -> Message:
    rows = sorted(rows, key=lambda r: r.submitted_at)
    head = "1 contribution is" if len(rows) == 1 else f"{len(rows)} contributions are"
    lines = [f"- {PART_NAMES[r.part]} for page {r.page_id}, from {neutral(r.name)}" for r in rows]
    text = f"{head} waiting for approval in the sheet:\n" + "\n".join(lines)
    key = f"pending:{len(rows)}:{rows[-1].submitted_at.isoformat()}"
    return _single(key, "pending", now.date(), text)


def _problem_digest(problems: list[str], log: dict, now: datetime) -> Message | None:
    new: dict[str, str] = {}
    for problem in problems:
        key = f"problem:{_sha1(problem)}"
        if key not in log:
            new.setdefault(key, problem)
    if not new:
        return None
    head = "The sheet has a new problem:" if len(new) == 1 else f"The sheet has {len(new)} new problems:"
    # A problem quotes the cell it is about, so each line is made inert. Its
    # key still hashes the raw text, as the log has always recorded it.
    text = head + "\n" + "\n".join(f"- {neutral(problem)}" for problem in new.values())
    return Message(tuple(Announcement(key, "problem", now.date(), text) for key in new), text)


def _single(key: str, kind: str, day: date, text: str) -> Message:
    return Message((Announcement(key, kind, day, text),), text)


def _day(day: date) -> str:
    return f"{day.day} {day.strftime('%B')}"


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _describe(error: Exception) -> str:
    """The error's type and HTTP status only. A requests HTTPError's text
    embeds the URL it failed on, and the webhook URL is a secret."""
    status = getattr(getattr(error, "response", None), "status_code", None)
    return type(error).__name__ + (f", HTTP {status}" if status else "")


# -- entry point -------------------------------------------------------------------

COMMANDS = {"sync": cmd_sync, "build": cmd_build, "announce": cmd_announce}
USAGE = "usage: python -m sync.cli {sync|build|announce}"

# The commands that post and push. Run by accident on a laptop, one gains
# nothing and can burn log keys in the real repository for good, so outside
# GitHub Actions they need an explicit opt-in.
ACTING = ("sync", "announce")
LOCAL_OPT_IN = "JOURNAL_CLUB_LOCAL"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] not in COMMANDS:
        print(USAGE, file=sys.stderr)
        return 2
    if (argv[0] in ACTING and os.environ.get("GITHUB_ACTIONS") != "true"
            and os.environ.get(LOCAL_OPT_IN) != "1"):
        print(f"Not running '{argv[0]}' outside GitHub Actions. It commits and pushes "
              "data/announcements.json before each message, and a message recorded "
              "there is never posted by the workflow. To do the workflow's job by "
              f"hand, set {LOCAL_OPT_IN}=1.", file=sys.stderr)
        return 2
    return COMMANDS[argv[0]]()


if __name__ == "__main__":
    sys.exit(main())
