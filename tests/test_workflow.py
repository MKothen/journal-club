from pathlib import Path

import yaml

WORKFLOW = yaml.safe_load(Path(".github/workflows/sync.yml").read_text(encoding="utf-8"))
STEPS = WORKFLOW["jobs"]["sync"]["steps"]


def step(name):
    return [s for s in STEPS if s.get("name") == name][0]


def index(name):
    return next(i for i, s in enumerate(STEPS) if s.get("name") == name)


def test_runs_are_queued_rather_than_overlapped():
    assert WORKFLOW["concurrency"]["group"] == "journal-club-sync"
    assert WORKFLOW["concurrency"]["cancel-in-progress"] is False


def test_it_runs_on_a_schedule_and_on_demand():
    assert "schedule" in WORKFLOW[True]
    assert "workflow_dispatch" in WORKFLOW[True]


def test_announcements_survive_a_failed_build_or_deploy():
    assert step("Announce")["if"] == "always()"
    assert step("Ping the monitor")["if"] == "always()"


def test_a_failure_is_reported_to_mattermost():
    assert step("Report failure")["if"] == "failure()"
    assert step("Report failure")["run"].strip().endswith("|| true")


def test_git_identity_is_configured_before_sync_runs():
    # Ruling 1: sync's own commit (git_persist) needs a working identity on
    # its very first invocation, so the identity step must run, and must run
    # before Sync, not only inside "Commit the archive" further down.
    assert index("Configure git identity") < index("Sync")


def test_sync_has_a_timeout_so_a_stalled_run_cannot_block_every_later_one():
    # Ruling 2: the concurrency group queues rather than cancels, so a single
    # hung Sync (a slow-drip explainer host) would block every run after it.
    assert step("Sync")["timeout-minutes"] == 10


def test_commit_the_archive_and_build_only_run_after_a_successful_sync():
    # Ruling 4: a failed Sync may have left data half-written; a half-written
    # site must not be committed or deployed. Neither step should carry an
    # always()/failure() override -- the default (prior steps succeeded) is
    # what we want.
    assert "if" not in step("Commit the archive")
    assert "if" not in step("Build")


def test_announce_does_not_duplicate_the_persist_that_the_cli_now_does_itself():
    # Ruling 4: `announce` persists data/announcements.json itself through
    # git_persist before each post, so the workflow step must not also
    # commit and push it.
    run = step("Announce")["run"]
    assert "git add" not in run
    assert "git commit" not in run
    assert "git push" not in run
    assert "python -m sync.cli announce" in run
