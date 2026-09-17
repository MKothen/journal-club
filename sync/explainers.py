"""Explainers are submitted content that executes. They are stored as text so
that no runnable copy exists on the site's origin, and the page runs them only
inside a sandboxed frame."""

import re
from pathlib import Path

import requests

from sync.config import EXPLAINER_MAX_BYTES

DRIVE_FILE = re.compile(r"drive\.google\.com/file/d/([^/]+)")
DRIVE_OPEN = re.compile(r"drive\.google\.com/open\?id=([^&]+)")


class ExplainerError(Exception):
    pass


def download_url(url: str) -> str:
    for pattern in (DRIVE_FILE, DRIVE_OPEN):
        match = pattern.search(url)
        if match:
            return f"https://drive.google.com/uc?export=download&id={match.group(1)}"
    return url


def http_get_text(url: str) -> str:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.text


def fetch_explainer(url: str, fetch=http_get_text) -> str:
    if not url.lower().startswith("https://"):
        raise ExplainerError("explainer links must use https")
    body = fetch(download_url(url))
    if len(body.encode("utf-8")) > EXPLAINER_MAX_BYTES:
        raise ExplainerError("explainer file is too large")
    head = body[:2000].lower()
    if "<html" not in head and "<!doctype html" not in head:
        raise ExplainerError("explainer content is not HTML")
    return body


def store_explainer(root: Path, page_id: str, html: str) -> Path:
    folder = root / "explainers" / page_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "explainer.txt"
    path.write_text(html, encoding="utf-8")
    return path
