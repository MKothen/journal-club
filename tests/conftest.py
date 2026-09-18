import pytest

# The workflow's environment changes what sync.cli and sync.mattermost do:
# they append to the files GitHub names here, and refuse to act locally
# without an opt-in. Every test starts outside Actions and without it, and
# sets what it needs.
WORKFLOW_ENVIRONMENT = ("GITHUB_ACTIONS", "GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY",
                        "JOURNAL_CLUB_LOCAL")


@pytest.fixture(autouse=True)
def outside_the_workflow(monkeypatch):
    for name in WORKFLOW_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
