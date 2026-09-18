"""Incoming webhook posting, with a printed fallback.

Posts go out through the club's own webhook, so anything a person typed into
the public form must reach the channel inert: `neutral` is applied to every
person-supplied value (names, paper titles, DOIs, and each problem line that
quotes a cell), and never to a URL or to the system's own wording.
"""

import requests

# Characters Mattermost Markdown could read as formatting, a link, an image,
# a heading, a quote, a table or raw HTML. The backslash is escaped too, so a
# typed backslash cannot undo the escape that follows it.
MARKDOWN_CHARACTERS = frozenset("\\`*_~[]()#>|!<")
ZERO_WIDTH_SPACE = "​"


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
        print("MATTERMOST (not configured), paste this:\n" + text)
        return False
    response = poster(webhook_url, json={"text": text}, timeout=30)
    response.raise_for_status()
    return True
