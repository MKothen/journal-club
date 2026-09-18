import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "sync.yml").read_text(encoding="utf-8"))
STEPS = WORKFLOW["jobs"]["sync"]["steps"]


def step(name):
    return [s for s in STEPS if s.get("name") == name][0]


def step_using(action):
    return [s for s in STEPS if str(s.get("uses", "")).startswith(action)][0]


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


def test_the_identity_step_actually_configures_git():
    # A step named right that does nothing would still pass the ordering
    # test above, so pin its content too.
    run = step("Configure git identity")["run"]
    assert "git config user.name" in run
    assert "git config user.email" in run


def test_sync_has_a_timeout_so_a_stalled_run_cannot_block_every_later_one():
    # Ruling 2: the concurrency group queues rather than cancels, so a single
    # hung Sync (a slow-drip explainer host) would block every run after it.
    assert step("Sync")["timeout-minutes"] == 10


def test_build_and_announce_have_timeouts_too():
    # gspread has no default HTTP timeout, so a stalled sheet read in either
    # step would otherwise hold the queue for the 360-minute job default.
    assert step("Build")["timeout-minutes"] == 10
    assert step("Announce")["timeout-minutes"] == 10


def test_commit_the_archive_and_build_only_run_after_a_successful_sync():
    # Ruling 4: a failed Sync may have left data half-written; a half-written
    # site must not be committed or deployed. Neither step should carry an
    # always()/failure() override -- the default (prior steps succeeded) is
    # what we want.
    assert "if" not in step("Commit the archive")
    assert "if" not in step("Build")


def test_pages_steps_carry_no_condition_either():
    assert "if" not in step_using("actions/upload-pages-artifact")
    assert "if" not in step_using("actions/deploy-pages")


def test_announce_does_not_duplicate_the_persist_that_the_cli_now_does_itself():
    # Ruling 4: `announce` persists data/announcements.json itself through
    # git_persist before each post, so the workflow step must not also
    # commit and push it.
    run = step("Announce")["run"]
    assert "git add" not in run
    assert "git commit" not in run
    assert "git push" not in run
    assert "python -m sync.cli announce" in run


def test_checkout_takes_the_branch_tip_at_run_time_not_the_trigger_time_sha():
    # Without ref:, checkout fetches exactly the trigger-time github.sha. A
    # run queued behind another under cancel-in-progress: false -- a manual
    # dispatch during the scheduled run, or the next schedule landing on a
    # stalled one -- would then start from a commit that predates the
    # earlier run's pushes, and its own first push would be rejected.
    checkout = step_using("actions/checkout")
    assert checkout["with"]["ref"] == "${{ github.ref }}"


def test_commit_the_archive_tolerates_a_repository_with_no_explainers_yet():
    # Critical: explainers/ is untracked until the first explainer is
    # fetched. `git add data explainers` on a checkout with no explainers/
    # directory at all exits 128 ("pathspec 'explainers' did not match any
    # files") under bash -e, which is the default run: shell, so nothing is
    # staged, "Commit the archive" fails, and the site never deploys. mkdir
    # -p is belt-and-braces alongside tracking explainers/.gitkeep in the
    # repository itself.
    run = step("Commit the archive")["run"]
    assert "mkdir -p explainers" in run
    tracked = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", "ls-files", "explainers/.gitkeep"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert tracked == "explainers/.gitkeep"


def test_no_secret_is_interpolated_directly_into_a_run_script():
    # A "$VAR" pulled from env: is safe even if a value ever contained a
    # quote or a $(); a secret spliced straight into the script text by
    # ${{ }} is substituted before the shell parses it.
    for s in STEPS:
        assert "${{ secrets." not in s.get("run", "")


def test_a_notice_that_was_not_posted_fails_the_run_after_announce():
    # Final review D8: Sync stays green when only a post failed, so the site
    # is still committed and built, and this step turns the run red after
    # the announcements, so Report failure and the monitor both hear of it.
    assert step("Sync")["id"] == "sync"
    check = step("Fail if a notice was not posted")
    assert check["if"].startswith("always()")
    assert "steps.sync.outputs.notices_failed" in check["if"]
    assert check["run"].strip() == "exit 1"
    assert index("Announce") < index("Fail if a notice was not posted")
    assert index("Fail if a notice was not posted") < index("Ping the monitor")
    assert index("Fail if a notice was not posted") < index("Report failure")
