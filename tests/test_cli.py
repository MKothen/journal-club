import hashlib
import json
import subprocess
from datetime import date, datetime

import pytest
import requests

from sync.announce import Announcement
from sync.claims import claim_key
from sync.cli import (
    COMMANDS,
    Effects,
    Message,
    PersistFailed,
    cmd_announce,
    cmd_build,
    cmd_sync,
    deliver,
    git_persist,
    main,
)
from sync.config import AMSTERDAM
from sync.explainers import ExplainerError
from tests.test_assemble import HEADER, row
from tests.test_sheet import reader

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=AMSTERDAM)
WEDNESDAY_MORNING = datetime(2026, 10, 14, 9, 0, tzinfo=AMSTERDAM)

HTML = "<!doctype html><html><body>first explainer</body></html>"
NEWER_HTML = "<!doctype html><html><body>second explainer</body></html>"
GOOD = "https://example.org/good.html"
NEWER = "https://example.org/newer.html"
BAD = "https://example.org/bad.html"
CSL = {"title": "A paper", "author": [{"given": "Ann", "family": "Author"}],
       "issued": {"date-parts": [[2025]]}, "container-title": "Journal"}


def claim(when, day, name, fmt="full", doi=""):
    cells = row(when, "claim", day, name, fmt=fmt)
    cells[5] = doi
    return cells


def part(when, page, name, kind, text="", link="", status="approved"):
    cells = row(when, "page", page, name, part=kind, text=text, status=status)
    cells[9] = link
    return cells


def sha1(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def read(root, name):
    return json.loads((root / "data" / name).read_text(encoding="utf-8"))


class Outside:
    """Every external effect, recorded in order. Nothing here touches the
    network, git or a real sheet. `rows` and `tabs` may be changed between
    runs to model the sheet changing."""

    def __init__(self, *rows, root=None, explainers=None, dois=None,
                 persist_fails=False, post_fails=False, **tabs):
        self.rows = list(rows)
        self.tabs = dict(tabs)
        self.root = root
        self.explainers = dict(explainers or {})
        self.dois = dict(dois or {})
        self.persist_fails = persist_fails
        self.post_fails = post_fails
        self.calls = []
        self.posts = []
        self.fetched = []
        self.persisted_logs = []

    def effects(self, now=NOW):
        return Effects(
            reader=reader(Responses=[HEADER, *self.rows], **self.tabs),
            now=now,
            persist=self.persist,
            send=self.send,
            get_explainer=self.get_explainer,
            get_doi=self.get_doi,
        )

    def persist(self):
        self.calls.append("persist")
        if self.root is not None:
            self.persisted_logs.append(read(self.root, "announcements.json"))
        if self.persist_fails:
            raise subprocess.CalledProcessError(1, ["git", "push"])

    def send(self, text):
        self.calls.append("post")
        if self.post_fails:
            raise RuntimeError("webhook returned 500")
        self.posts.append(text)

    def get_explainer(self, url):
        self.fetched.append(url)
        body = self.explainers[url]
        if isinstance(body, Exception):
            raise body
        return body

    def get_doi(self, url, headers):
        doi = url.removeprefix("https://doi.org/")
        self.fetched.append(doi)
        result = self.dois[doi]
        if isinstance(result, Exception):
            raise result
        return result


# -- sync writes the archive and the paper cache ------------------------------

def test_sync_writes_the_archive_and_caches_paper_metadata(tmp_path):
    outside = Outside(claim("2026-09-20 09:00:00", "2026-10-28", "Ann", doi="10.1000/xyz"),
                      dois={"10.1000/xyz": CSL})
    assert cmd_sync(tmp_path, outside.effects()) == 0

    assert read(tmp_path, "papers/cache.json")["10.1000/xyz"]["title"] == "A paper"
    assert list(read(tmp_path, "slots.json").values()) == ["2026-10-28"]
    for name in ("schedule.json", "submissions.json", "sync_state.json"):
        assert (tmp_path / "data" / name).exists()
    assert outside.posts == []


def test_a_run_with_nothing_to_post_never_touches_git(tmp_path):
    outside = Outside()
    assert cmd_sync(tmp_path, outside.effects()) == 0
    assert cmd_announce(tmp_path, outside.effects()) == 0
    assert outside.calls == []
    assert not (tmp_path / "data" / "announcements.json").exists()


GUEST_SESSION = {"Open sessions": [
    ["date", "title", "guest", "affiliation", "doi", "length_minutes"],
    ["2026-10-28", "Guest talk", "A. Author", "Elsewhere", "https://doi.org/10.1000/Guest", "90"],
]}


def test_sync_caches_the_paper_of_an_open_session_too(tmp_path):
    outside = Outside(dois={"10.1000/guest": CSL}, **GUEST_SESSION)
    assert cmd_sync(tmp_path, outside.effects()) == 0
    assert read(tmp_path, "papers/cache.json")["10.1000/guest"]["title"] == "A paper"


def test_a_failed_open_session_lookup_is_retried_next_run_like_any_other(tmp_path):
    outside = Outside(claim("2026-09-21 09:00:00", "2026-11-25", "Cy", doi="10.1000/good"),
                      dois={"10.1000/guest": ConnectionError("doi.org timed out"),
                            "10.1000/good": CSL},
                      **GUEST_SESSION)
    assert cmd_sync(tmp_path, outside.effects()) == 0
    assert list(read(tmp_path, "papers/cache.json")) == ["10.1000/good"]

    outside.dois["10.1000/guest"] = CSL
    assert cmd_sync(tmp_path, outside.effects()) == 0
    assert sorted(read(tmp_path, "papers/cache.json")) == ["10.1000/good", "10.1000/guest"]
    assert outside.fetched.count("10.1000/good") == 1


# -- R9: one page's failure never stops the others ------------------------------

def test_a_failed_doi_lookup_does_not_stop_the_others_and_is_retried_next_run(tmp_path):
    outside = Outside(claim("2026-09-20 09:00:00", "2026-10-28", "Ann", doi="10.1000/bad"),
                      claim("2026-09-21 09:00:00", "2026-11-11", "Cy", doi="10.1000/good"),
                      dois={"10.1000/bad": ConnectionError("doi.org timed out"),
                            "10.1000/good": CSL})
    assert cmd_sync(tmp_path, outside.effects()) == 0
    assert list(read(tmp_path, "papers/cache.json")) == ["10.1000/good"]

    outside.dois["10.1000/bad"] = CSL
    assert cmd_sync(tmp_path, outside.effects()) == 0
    assert sorted(read(tmp_path, "papers/cache.json")) == ["10.1000/bad", "10.1000/good"]
    assert outside.fetched.count("10.1000/good") == 1


def test_a_failed_explainer_does_not_stop_the_other_pages(tmp_path):
    outside = Outside(part("2026-10-15 09:00:00", "2026-10-14", "Ann", "explainer", link=BAD),
                      part("2026-10-15 10:00:00", "2026-10-28", "Cy", "explainer", link=GOOD),
                      explainers={BAD: ExplainerError("host resolves to a private or reserved address"),
                                  GOOD: HTML})
    assert cmd_sync(tmp_path, outside.effects()) == 0

    stored = tmp_path / "explainers" / "2026-10-28" / "explainer.txt"
    assert stored.read_text(encoding="utf-8") == HTML
    assert not (tmp_path / "explainers" / "2026-10-14").exists()
    assert (tmp_path / "data" / "slots.json").exists()
    assert len(outside.posts) == 1
    assert "2026-10-14" in outside.posts[0] and "private or reserved" in outside.posts[0]


# -- R8: explainers are fetched only when their link changes -------------------

def test_an_explainer_is_fetched_again_only_when_its_link_changes(tmp_path):
    outside = Outside(part("2026-10-15 09:00:00", "2026-10-14", "Ann", "explainer", link=GOOD),
                      explainers={GOOD: HTML, NEWER: NEWER_HTML})
    cmd_sync(tmp_path, outside.effects())
    cmd_sync(tmp_path, outside.effects())
    assert outside.fetched == [GOOD]
    assert read(tmp_path, "explainers.json") == {"2026-10-14": GOOD}

    outside.rows.append(part("2026-10-16 09:00:00", "2026-10-14", "Ann", "explainer", link=NEWER))
    cmd_sync(tmp_path, outside.effects())
    assert outside.fetched == [GOOD, NEWER]
    stored = tmp_path / "explainers" / "2026-10-14" / "explainer.txt"
    assert stored.read_text(encoding="utf-8") == NEWER_HTML


def test_an_unapproved_explainer_link_is_never_fetched(tmp_path):
    outside = Outside(part("2026-10-15 09:00:00", "2026-10-14", "Ann", "explainer",
                           link=GOOD, status=""),
                      explainers={GOOD: HTML})
    cmd_sync(tmp_path, outside.effects())
    assert outside.fetched == []


def test_a_recorded_explainer_whose_file_is_gone_is_fetched_again(tmp_path):
    outside = Outside(part("2026-10-15 09:00:00", "2026-10-14", "Ann", "explainer", link=GOOD),
                      explainers={GOOD: HTML})
    cmd_sync(tmp_path, outside.effects())
    (tmp_path / "explainers" / "2026-10-14" / "explainer.txt").unlink()
    cmd_sync(tmp_path, outside.effects())
    assert outside.fetched == [GOOD, GOOD]


def test_a_failed_explainer_is_retried_every_run_but_reported_once(tmp_path):
    signin = ExplainerError("explainer link shows a Google sign-in page")
    outside = Outside(part("2026-10-15 09:00:00", "2026-10-14", "Ann", "explainer", link=BAD),
                      explainers={BAD: signin})
    cmd_sync(tmp_path, outside.effects())
    cmd_sync(tmp_path, outside.effects())
    assert outside.fetched == [BAD, BAD]
    assert len(outside.posts) == 1
    assert read(tmp_path, "announcements.json")[
        f"explainer-failed:2026-10-14:{sha1(BAD)}"]["state"] == "sent"

    # The presenter fixes the sharing setting; the link itself is unchanged.
    outside.explainers[BAD] = HTML
    cmd_sync(tmp_path, outside.effects())
    assert (tmp_path / "explainers" / "2026-10-14" / "explainer.txt").exists()
    assert read(tmp_path, "explainers.json") == {"2026-10-14": BAD}


def test_an_explainer_failure_quoting_a_hostile_link_mentions_nobody(tmp_path):
    # An ExplainerError can echo part of the link, and the link came from the form.
    hostile = ExplainerError("could not fetch https://evil.example/x/@channel/[win](https://evil.example)")
    outside = Outside(part("2026-10-15 09:00:00", "2026-10-14", "Ann", "explainer", link=BAD),
                      explainers={BAD: hostile})
    cmd_sync(tmp_path, outside.effects())
    assert len(outside.posts) == 1
    assert "@channel" not in outside.posts[0]
    assert "[win](" not in outside.posts[0]


def test_a_failed_newer_link_keeps_the_older_file_and_is_retried(tmp_path):
    outside = Outside(part("2026-10-15 09:00:00", "2026-10-14", "Ann", "explainer", link=GOOD),
                      explainers={GOOD: HTML, NEWER: ExplainerError("explainer file is too large")})
    cmd_sync(tmp_path, outside.effects())
    outside.rows.append(part("2026-10-16 09:00:00", "2026-10-14", "Ann", "explainer", link=NEWER))
    cmd_sync(tmp_path, outside.effects())
    stored = tmp_path / "explainers" / "2026-10-14" / "explainer.txt"
    assert stored.read_text(encoding="utf-8") == HTML
    assert read(tmp_path, "explainers.json") == {"2026-10-14": GOOD}

    outside.explainers[NEWER] = NEWER_HTML
    cmd_sync(tmp_path, outside.effects())
    assert outside.fetched == [GOOD, NEWER, NEWER]
    assert stored.read_text(encoding="utf-8") == NEWER_HTML


# -- R3: nothing from sync is posted twice --------------------------------------

def test_a_rejected_claim_is_posted_once_and_names_the_next_open_session(tmp_path):
    outside = Outside(claim("2026-09-20 09:00:00", "2026-10-28", "Ann"),
                      claim("2026-09-22 09:00:00", "2026-10-28", "Cy"))
    cmd_sync(tmp_path, outside.effects())
    cmd_sync(tmp_path, outside.effects())

    assert len(outside.posts) == 1
    assert outside.posts[0].startswith("Cy")
    assert "https://example.github.io/journal-club/sessions/2026-11-11/" in outside.posts[0]
    key = claim_key({"submitted_at": datetime(2026, 9, 22, 9, 0, tzinfo=AMSTERDAM), "name": "Cy"})
    assert read(tmp_path, "announcements.json")[f"reject:{key}"]["state"] == "sent"


def test_a_rejection_links_the_next_open_sessions_page_when_its_date_id_is_retired(tmp_path):
    ann = claim("2026-09-20 09:00:00", "2026-10-28", "Ann")
    outside = Outside(ann)
    cmd_sync(tmp_path, outside.effects())

    # Ann's claim is hidden, so 28 October is open again under a new page id.
    outside.rows[0] = ann[:11] + ["yes"] + ann[12:]
    outside.rows += [claim("2026-09-21 09:00:00", "2026-11-11", "Bo"),
                     claim("2026-09-22 09:00:00", "2026-11-11", "Cy")]
    cmd_sync(tmp_path, outside.effects())
    assert len(outside.posts) == 1 and outside.posts[0].startswith("Cy")
    assert "https://example.github.io/journal-club/sessions/2026-10-28-2/" in outside.posts[0]


# -- final review I4: public form text never formats or notifies in Mattermost -----

EVIL_NAME = "@channel\n[win](https://e.vil)"
EVIL_TITLE = "![x](https://e.vil/p.png)"


def test_form_text_reaches_mattermost_inert_in_every_post_that_quotes_it(tmp_path):
    placed = claim("2026-09-20 09:00:00", "2026-10-28", EVIL_NAME)
    placed[8] = EVIL_TITLE
    outside = Outside(
        placed,
        claim("2026-09-21 09:00:00", "2026-10-28", EVIL_NAME),       # not placed
        part("2026-10-15 09:00:00", "2026-10-28", EVIL_NAME, "synthesis",
             text="Mine", status=""),                                  # waits for approval
        row("2026-10-15 10:00:00", "takeaway", "2026-10-09", EVIL_NAME,
            takeaway="Wrong page"),                                    # a sheet problem
    )
    cmd_sync(tmp_path, outside.effects())
    cmd_announce(tmp_path, outside.effects(datetime(2026, 10, 26, 10, 0, tzinfo=AMSTERDAM)))

    kinds = ["not placed", "waiting for approval", "The sheet has", "claimed", "This Wednesday"]
    assert [next(k for k in kinds if k in post) for post in outside.posts] == kinds
    inert = "@" + chr(0x200B) + "channel " + chr(92) + "[win" + chr(92) + "]"
    for post in outside.posts:
        assert inert in post
        assert "@channel" not in post and "](" not in post and "![" not in post
        assert "channel\n" not in post
    assert outside.posts[1].count("\n") == 1     # the heading, then one line
    assert outside.posts[2].count("\n") == 1


def test_the_approval_nag_posts_once_per_change_in_the_pending_set(tmp_path):
    outside = Outside(part("2026-10-15 09:00:00", "2026-10-14", "Ann", "synthesis",
                           text="We were not convinced", status=""))
    cmd_sync(tmp_path, outside.effects())
    cmd_sync(tmp_path, outside.effects())
    assert len(outside.posts) == 1
    assert "1 contribution is waiting for approval" in outside.posts[0]
    assert "pending:1:2026-10-15T09:00:00+02:00" in read(tmp_path, "announcements.json")

    outside.rows.append(part("2026-10-16 09:00:00", "2026-10-14", "Prof", "reply",
                             text="I wrote the paper", status=""))
    cmd_sync(tmp_path, outside.effects())
    assert len(outside.posts) == 2
    assert "2 contributions are waiting for approval" in outside.posts[1]
    assert "pending:2:2026-10-16T09:00:00+02:00" in read(tmp_path, "announcements.json")


def test_sheet_problems_are_posted_as_one_digest_of_only_the_new_ones(tmp_path):
    outside = Outside(row("2026-10-14 12:00:00", "takeaway", "2026-10-09", "Bo", takeaway="x"),
                      **{"Session status": [["date", "status"], ["2026-11-11", "maybe"]]})
    cmd_sync(tmp_path, outside.effects())
    cmd_sync(tmp_path, outside.effects())
    assert len(outside.posts) == 1
    assert "2026-10-09" in outside.posts[0]         # R6: the orphaned takeaway
    assert "maybe" in outside.posts[0]              # a Task 9 sheet problem

    outside.tabs["Skipped weeks"] = [["date"], ["7 Oct"]]
    cmd_sync(tmp_path, outside.effects())
    assert len(outside.posts) == 2
    assert "7 Oct" in outside.posts[1]
    assert "maybe" not in outside.posts[1] and "2026-10-09" not in outside.posts[1]

    log = read(tmp_path, "announcements.json")
    problems = [key for key in log if key.startswith("problem:")]
    assert len(problems) == 3
    assert all(len(key) == len("problem:") + 40 for key in problems)


def test_a_failed_post_from_sync_is_contained(tmp_path):
    outside = Outside(claim("2026-09-20 09:00:00", "2026-10-28", "Ann"),
                      claim("2026-09-22 09:00:00", "2026-10-28", "Cy"),
                      post_fails=True)
    assert cmd_sync(tmp_path, outside.effects()) == 0
    assert (tmp_path / "data" / "slots.json").exists()


# -- final review D8: a notice that was not posted fails the run, after the build ---

def test_a_failed_notice_leaves_sync_green_and_tells_the_workflow(tmp_path, monkeypatch, capsys):
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    outside = Outside(claim("2026-09-20 09:00:00", "2026-10-28", "Ann"),
                      claim("2026-09-22 09:00:00", "2026-10-28", "Cy"),
                      post_fails=True)
    assert cmd_sync(tmp_path, outside.effects()) == 0
    assert output.read_text(encoding="utf-8") == "notices_failed=1" + chr(10)
    assert ("::error::1 notice(s) could not be posted to Mattermost; see the sending "
            "entries in data/announcements.json") in capsys.readouterr().out


def test_a_sync_whose_notices_all_went_out_tells_the_workflow_nothing(tmp_path, monkeypatch):
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    outside = Outside(claim("2026-09-20 09:00:00", "2026-10-28", "Ann"),
                      claim("2026-09-22 09:00:00", "2026-10-28", "Cy"))
    assert cmd_sync(tmp_path, outside.effects()) == 0
    assert len(outside.posts) == 1
    assert not output.exists()


def test_sync_posts_nothing_and_fails_when_the_log_cannot_be_persisted(tmp_path):
    outside = Outside(claim("2026-09-20 09:00:00", "2026-10-28", "Ann"),
                      claim("2026-09-22 09:00:00", "2026-10-28", "Cy"),
                      persist_fails=True)
    assert cmd_sync(tmp_path, outside.effects()) == 1
    assert "post" not in outside.calls
    assert (tmp_path / "data" / "slots.json").exists()
    assert read(tmp_path, "announcements.json") == {}


# -- R4: the log reaches git before the post it guards ------------------------

def announcement(key="2026-10-14:claim", text="Ann claimed"):
    return Announcement(key, "claim", date(2026, 10, 14), text)


def test_the_log_is_persisted_before_the_post_and_once_more_at_the_end(tmp_path):
    outside = Outside(root=tmp_path)
    item = announcement()
    deliver([Message((item,), item.text)], {}, tmp_path / "data" / "announcements.json",
            outside.persist, outside.send)

    assert outside.calls == ["persist", "post", "persist"]
    assert outside.persisted_logs[0]["2026-10-14:claim"]["state"] == "sending"
    assert outside.persisted_logs[1]["2026-10-14:claim"]["state"] == "sent"


def test_a_persist_that_raises_means_post_is_never_called(tmp_path):
    outside = Outside(persist_fails=True)
    item = announcement()
    log = {}
    path = tmp_path / "data" / "announcements.json"
    with pytest.raises(PersistFailed):
        deliver([Message((item,), item.text)], log, path, outside.persist, outside.send)

    assert outside.calls == ["persist"]
    # Nothing was posted, so nothing is left at "sending": a later run may post it.
    assert log == {}
    assert json.loads(path.read_text(encoding="utf-8")) == {}


def test_two_posts_guarded_by_the_same_key_post_once(tmp_path):
    outside = Outside()
    item = announcement()
    deliver([Message((item,), item.text), Message((item,), item.text)], {},
            tmp_path / "data" / "announcements.json", outside.persist, outside.send)
    assert outside.posts == [item.text]


def test_a_digest_is_one_post_that_logs_every_key_it_guards(tmp_path):
    outside = Outside()
    first, second = announcement("problem:a", "digest"), announcement("problem:b", "digest")
    log = {}
    deliver([Message((first, second), "digest")], log, tmp_path / "data" / "announcements.json",
            outside.persist, outside.send)
    assert outside.posts == ["digest"]
    assert {log["problem:a"]["state"], log["problem:b"]["state"]} == {"sent"}


# -- R5: announce calls claim_announcements(now, ...) and marks superseded ------

def test_announce_posts_the_claim_and_the_newest_window_and_skips_the_older_one(tmp_path):
    outside = Outside(claim("2026-09-20 09:00:00", "2026-10-14", "Ann", fmt="help"))
    assert cmd_announce(tmp_path, outside.effects(WEDNESDAY_MORNING)) == 0

    assert outside.calls == ["persist", "post", "persist", "post", "persist"]
    assert "Ann claimed" in outside.posts[0]
    assert outside.posts[1].startswith("Today")
    log = read(tmp_path, "announcements.json")
    assert log["2026-10-14:claim"]["state"] == "sent"
    assert log["2026-10-14:wednesday"]["state"] == "sent"
    assert log["2026-10-14:monday"]["state"] == "skipped"
    assert "2026-10-14:friday" not in log


def test_a_second_announce_run_posts_nothing(tmp_path):
    outside = Outside(claim("2026-09-20 09:00:00", "2026-10-14", "Ann", fmt="help"))
    cmd_announce(tmp_path, outside.effects(WEDNESDAY_MORNING))
    cmd_announce(tmp_path, outside.effects(datetime(2026, 10, 14, 10, 0, tzinfo=AMSTERDAM)))
    assert len(outside.posts) == 2


def test_announce_uses_the_aliased_name(tmp_path):
    outside = Outside(claim("2026-09-20 09:00:00", "2026-10-14", "bo", fmt="help"),
                      Aliases=[["alias", "display name"], ["bo", "Bo de Vries"]])
    cmd_announce(tmp_path, outside.effects(WEDNESDAY_MORNING))
    assert all("Bo de Vries" in text for text in outside.posts)


def test_announce_posts_nothing_when_the_log_cannot_be_persisted(tmp_path):
    outside = Outside(claim("2026-09-20 09:00:00", "2026-10-14", "Ann", fmt="help"),
                      persist_fails=True)
    assert cmd_announce(tmp_path, outside.effects(WEDNESDAY_MORNING)) == 1
    assert "post" not in outside.calls
    states = [entry["state"] for entry in read(tmp_path, "announcements.json").values()]
    assert "sending" not in states


def test_a_failed_post_stays_at_sending_is_never_retried_and_fails_the_run(tmp_path):
    outside = Outside(claim("2026-09-20 09:00:00", "2026-10-14", "Ann", fmt="help"),
                      post_fails=True)
    assert cmd_announce(tmp_path, outside.effects(WEDNESDAY_MORNING)) == 1
    assert outside.calls.count("post") == 2
    log = read(tmp_path, "announcements.json")
    assert log["2026-10-14:claim"]["state"] == "sending"
    assert log["2026-10-14:wednesday"]["state"] == "sending"

    outside.post_fails = False
    cmd_announce(tmp_path, outside.effects(datetime(2026, 10, 14, 10, 0, tzinfo=AMSTERDAM)))
    assert outside.calls.count("post") == 2


def test_a_superseded_window_is_persisted_even_with_nothing_to_post(tmp_path):
    sent = {"state": "sent", "at": "2026-10-14T08:05:00+02:00"}
    path = tmp_path / "data" / "announcements.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"2026-10-14:claim": sent, "2026-10-14:wednesday": sent}),
                    encoding="utf-8")
    outside = Outside(claim("2026-09-20 09:00:00", "2026-10-14", "Ann", fmt="help"))
    assert cmd_announce(tmp_path, outside.effects(WEDNESDAY_MORNING)) == 0
    assert outside.calls == ["persist"]
    assert read(tmp_path, "announcements.json")["2026-10-14:monday"]["state"] == "skipped"


def test_a_failed_post_is_reported_without_the_webhook_url(tmp_path, capsys):
    response = requests.Response()
    response.status_code = 500

    def send(text):
        raise requests.HTTPError(
            "500 Server Error: Internal Server Error for url: https://mm.example/hooks/SECRET",
            response=response,
        )

    item = announcement()
    failed = deliver([Message((item,), item.text)], {}, tmp_path / "data" / "announcements.json",
                     Outside().persist, send)
    out = capsys.readouterr().out
    assert failed == 1
    assert "SECRET" not in out
    assert "HTTPError" in out and "500" in out


# -- the production persist ----------------------------------------------------

class FakeGit:
    def __init__(self, staged=True, failing=None):
        self.staged = staged
        self.failing = failing
        self.commands = []

    def __call__(self, argv, cwd=None, check=False, **kwargs):
        self.commands.append(argv)
        returncode = 0
        if argv[1] == "diff":
            returncode = 1 if self.staged else 0
        if argv[1] == self.failing:
            returncode = 128
        if check and returncode != 0:
            raise subprocess.CalledProcessError(returncode, argv)
        return subprocess.CompletedProcess(argv, returncode)


LOG = "data/announcements.json"


def test_persist_without_claim_records_commits_only_the_announcement_log(tmp_path):
    git = FakeGit(staged=True)
    git_persist(tmp_path, run=git)
    assert git.commands == [
        ["git", "add", LOG],
        ["git", "diff", "--cached", "--quiet", "--", LOG],
        ["git", "commit", "-m", "chore: announcement log", "--", LOG],
        ["git", "push"],
    ]


def test_persist_never_overrides_the_runners_repository_ownership(tmp_path):
    git = FakeGit(staged=True)
    git_persist(tmp_path, run=git)
    assert not any("safe.directory" in arg for argv in git.commands for arg in argv)


def test_persist_with_nothing_changed_makes_no_commit_but_still_pushes(tmp_path):
    git = FakeGit(staged=False)
    git_persist(tmp_path, run=git)
    assert [argv[1] for argv in git.commands] == ["add", "diff", "push"]


@pytest.mark.parametrize("failing", ["add", "diff", "commit", "push"])
def test_persist_raises_when_any_git_step_fails(tmp_path, failing):
    with pytest.raises(subprocess.CalledProcessError):
        git_persist(tmp_path, run=FakeGit(staged=True, failing=failing))


# -- final review D7: a refusal reaches git no later than its notice -----------------

@pytest.mark.parametrize("present", [["slots.json"], ["refused.json"], ["slots.json", "refused.json"]])
def test_persist_commits_the_claim_records_that_exist_with_the_log(tmp_path, present):
    (tmp_path / "data").mkdir()
    for name in present:
        (tmp_path / "data" / name).write_text("{}", encoding="utf-8")
    paths = [LOG] + [f"data/{name}" for name in ("slots.json", "refused.json") if name in present]
    git = FakeGit(staged=True)
    git_persist(tmp_path, run=git)
    assert git.commands == [
        ["git", "add", *paths],
        ["git", "diff", "--cached", "--quiet", "--", *paths],
        ["git", "commit", "-m", "chore: announcement log", "--", *paths],
        ["git", "push"],
    ]


def test_a_refused_claimant_is_never_placed_when_the_session_is_released(tmp_path):
    ann = claim("2026-09-20 09:00:00", "2026-10-28", "Ann")
    outside = Outside(ann, claim("2026-09-22 09:00:00", "2026-10-28", "Bo"))
    assert cmd_sync(tmp_path, outside.effects()) == 0
    assert len(outside.posts) == 1 and outside.posts[0].startswith("Bo")
    bo = claim_key({"submitted_at": datetime(2026, 9, 22, 9, 0, tzinfo=AMSTERDAM), "name": "Bo"})
    assert read(tmp_path, "refused.json") == [bo]

    # Ann's row is hidden, which releases the session, and Cy claims it.
    outside.rows[0] = ann[:11] + ["yes"] + ann[12:]
    outside.rows.append(claim("2026-09-23 09:00:00", "2026-10-28", "Cy"))
    assert cmd_sync(tmp_path, outside.effects()) == 0
    assert len(outside.posts) == 1
    assert bo not in read(tmp_path, "slots.json")

    assert cmd_announce(tmp_path, outside.effects()) == 0
    assert len(outside.posts) == 2
    assert outside.posts[1].startswith("Cy claimed")
    assert "/sessions/2026-10-28-2/" in outside.posts[1]


# -- build and the entry point --------------------------------------------------

def test_build_renders_from_the_sheet_and_touches_nothing_else(tmp_path):
    outside = Outside(claim("2026-09-20 09:00:00", "2026-10-28", "Ann"))
    seen = {}

    def render(root, built, data):
        seen.update(root=root, built=built, data=data)

    assert cmd_build(tmp_path, outside.effects(), render=render) == 0
    assert seen["root"] == tmp_path
    assert seen["built"].pages["2026-10-28"].slot.presenter == "Ann"
    assert seen["data"].settings.room == "Lab room"
    assert outside.calls == []
    assert not (tmp_path / "data").exists()


def test_the_three_workflow_commands_exist():
    assert set(COMMANDS) == {"sync", "build", "announce"}


@pytest.mark.parametrize("argv", [[], ["deploy"], ["sync", "extra"]])
def test_a_bad_command_line_prints_usage_and_exits_2(argv, capsys):
    assert main(argv) == 2
    assert "usage" in capsys.readouterr().err



# -- final review D5: sync and announce act only in the workflow, or on request -----

def refuse_production_effects():
    raise AssertionError("production_effects must not be built")


@pytest.mark.parametrize("command", ["sync", "announce"])
def test_a_local_sync_or_announce_is_refused_without_the_opt_in(command, monkeypatch, capsys):
    monkeypatch.setattr("sync.cli.production_effects", refuse_production_effects)
    assert main([command]) == 2
    assert "JOURNAL_CLUB_LOCAL=1" in capsys.readouterr().err


class Proceeded(Exception):
    pass


def proceed():
    raise Proceeded


@pytest.mark.parametrize("variable, value", [("GITHUB_ACTIONS", "true"), ("JOURNAL_CLUB_LOCAL", "1")])
@pytest.mark.parametrize("command", ["sync", "announce"])
def test_in_the_workflow_or_with_the_opt_in_the_command_runs(command, variable, value, monkeypatch):
    monkeypatch.setenv(variable, value)
    monkeypatch.setattr("sync.cli.production_effects", proceed)
    with pytest.raises(Proceeded):
        main([command])


def test_build_needs_no_opt_in(monkeypatch):
    monkeypatch.setattr("sync.cli.production_effects", proceed)
    with pytest.raises(Proceeded):
        main(["build"])
