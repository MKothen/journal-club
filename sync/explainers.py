"""Explainers are submitted content that executes. They are stored as text so
that no runnable copy exists on the site's origin, and the page runs them only
inside a sandboxed frame."""

import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

import requests

from sync.config import EXPLAINER_MAX_BYTES

DRIVE_FILE = re.compile(r"drive\.google\.com/file/d/([^/]+)")
DRIVE_OPEN = re.compile(r"drive\.google\.com/open\?id=([^&]+)")
PAGE_ID_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}(?:-(?:[a-z]|\d+))?$")


class ExplainerError(Exception):
    pass


def download_url(url: str) -> str:
    for pattern in (DRIVE_FILE, DRIVE_OPEN):
        match = pattern.search(url)
        if match:
            return f"https://drive.google.com/uc?export=download&id={match.group(1)}"
    return url


def check_host(url: str, resolver=socket.getaddrinfo) -> None:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise ExplainerError("invalid URL")
    try:
        addresses = resolver(host, None)
    except socket.gaierror:
        raise ExplainerError("host could not be resolved")
    for addr_info in addresses:
        addr = addr_info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
            if (ip.is_private or ip.is_loopback or ip.is_link_local or
                ip.is_reserved or ip.is_multicast):
                raise ExplainerError("host resolves to a private or reserved address")
        except ValueError:
            pass


def http_get_text(url: str, http_client=None) -> str:
    if http_client is None:
        http_client = requests.get
    response = http_client(url, stream=True, timeout=60, allow_redirects=False)
    response.raise_for_status()
    if "charset" not in response.headers.get("content-type", "").lower():
        response.encoding = "utf-8"
    accumulated = b""
    for chunk in response.iter_content(chunk_size=65536):
        if chunk:
            accumulated += chunk
            if len(accumulated) > EXPLAINER_MAX_BYTES:
                raise ExplainerError("explainer file is too large")
    return accumulated.decode(response.encoding or "utf-8")


def fetch_explainer(url: str, fetch=http_get_text, resolver=socket.getaddrinfo) -> str:
    if not url.lower().startswith("https://"):
        raise ExplainerError("explainer links must use https")
    check_host(url, resolver)
    current_url = url
    hops = 0
    while hops < 3:
        body = fetch(download_url(current_url))
        if len(body.encode("utf-8")) > EXPLAINER_MAX_BYTES:
            raise ExplainerError("explainer file is too large")
        parsed = urlparse(download_url(current_url))
        if parsed.hostname == "accounts.google.com":
            raise ExplainerError("explainer link redirects to Google sign-in; set file sharing to 'anyone with the link'")
        if "Virus scan warning" in body or "Sign in - Google Accounts" in body:
            raise ExplainerError("explainer link redirects to Google sign-in; set file sharing to 'anyone with the link'")
        head = body[:2000].lower()
        if "<html" not in head and "<!doctype html" not in head:
            raise ExplainerError("explainer content is not HTML")
        return body
    raise ExplainerError("too many redirects")


def store_explainer(root: Path, page_id: str, html: str) -> Path:
    if not PAGE_ID_PATTERN.match(page_id):
        raise ExplainerError("invalid page ID format")
    folder = root / "explainers" / page_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "explainer.txt"
    path.write_text(html, encoding="utf-8", newline="")
    return path
