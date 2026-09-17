"""Incoming webhook posting, with a printed fallback."""

import requests


def post(text: str, webhook_url: str | None, poster=requests.post) -> bool:
    if not webhook_url:
        print("MATTERMOST (not configured), paste this:\n" + text)
        return False
    response = poster(webhook_url, json={"text": text}, timeout=30)
    response.raise_for_status()
    return True
