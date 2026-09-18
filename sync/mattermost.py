"""Incoming webhook posting, with a fallback for when there is no webhook.

Without a webhook, spec section 8's fallback applies: each message is added
to the workflow run's summary page for someone to paste, and printed to the
step log. The caller still records it as sent, so it is never posted later
when the webhook is added.

Posts go out through the club's own webhook, so anything a person typed into
the public form must reach the channel inert: `neutral` is applied to every
person-supplied value (names, paper titles, DOIs, and each problem line that
quotes a cell), and never to a URL or to the system's own wording.
"""

import os

import requests

# Characters Mattermost Markdown could read as formatting, a link, an image,
# a heading, a quote, a table or raw HTML. The backslash is escaped too, so a
# typed backslash cannot undo the escape that follows it.
MARKDOWN_CHARACTERS = frozenset("\\`*_~[]()#>|!<")
ZERO_WIDTH_SPACE = chr(0x200B)


def neutral(text: str) -> str:
    """Person-supplied text as it may appear in a post: all whitespace,
    newlines included, collapsed to single spaces, so it cannot add lines;
    a zero-width space after every @, so "@channel" or "@all" notifies
    nobody; and every Markdown character backslash-escaped, so a name or a
    title cannot become a link or an image. Mattermost renders an escaped
    character as the character itself."""
    flat = " ".join(text.split())
    escaped = "".join("\\" + c if c in MARKDOWN_CHARACTERS else c for c in flat)
    return escaped.replace("@", "@" + ZERO_WIDTH_SPACE)


def post(text: str, webhook_url: str | None, poster=requests.post) -> bool:
    if not webhook_url:
        _add_to_run_summary(text)
        print("MATTERMOST (not configured), paste this:\n" + text)
        return False
    response = poster(webhook_url, json={"text": text}, timeout=30)
    response.raise_for_status()
    return True


FENCE = "`" * 3


def _add_to_run_summary(text: str) -> None:
    """Append the message to $GITHUB_STEP_SUMMARY, when the workflow sets it,
    as a plain-text code block: a public repository's run summary is public,
    and inside the block a name or a title is shown, not rendered as
    Markdown. Three backticks in a row could close the block, so each such
    run is replaced by three apostrophes first."""
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary:
        return
    body = text.replace(FENCE, "'''")
    with open(summary, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{FENCE}text\n{body}\n{FENCE}\n\n")
