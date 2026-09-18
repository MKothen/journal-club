"""Explainers are submitted content that executes. They are stored as text so
that no runnable copy exists on the site's origin, and the page runs them only
inside a sandboxed frame.

Network safety (host checks, redirect handling, the Google Drive interstitial's
final host) all lives in the fetcher, http_get_text. fetch_explainer only
inspects content that has already been fetched: size, whether it is HTML, and
the Drive interstitial body markers. A stub fetch passed into fetch_explainer
therefore does no DNS lookups at all, which is what keeps the tests offline.
"""

import codecs
import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from sync.config import EXPLAINER_MAX_BYTES

DRIVE_FILE = re.compile(r"drive\.google\.com/file/d/([^/]+)")
DRIVE_OPEN = re.compile(r"drive\.google\.com/open\?id=([^&]+)")
PAGE_ID_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}(?:-(?:[a-z]|\d+))?$")

MAX_REDIRECTS = 3

GOOGLE_SIGNIN_MESSAGE = (
    "explainer link shows a Google sign-in page; "
    "set file sharing to 'anyone with the link'"
)
GOOGLE_VIRUS_SCAN_MESSAGE = (
    "explainer link shows Google's virus-scan warning page; "
    "the file may be too large for Drive to scan automatically"
)


class ExplainerError(Exception):
    pass


def download_url(url: str) -> str:
    for pattern in (DRIVE_FILE, DRIVE_OPEN):
        match = pattern.search(url)
        if match:
            return f"https://drive.google.com/uc?export=download&id={match.group(1)}"
    return url


def check_host(url: str, resolver=socket.getaddrinfo) -> None:
    """Fail closed: block anything that is not a globally routable address,
    an address the resolver could not classify, or a host with no
    addresses at all."""
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise ExplainerError("invalid URL")
    try:
        addresses = resolver(host, None)
    except socket.gaierror:
        raise ExplainerError("host could not be resolved")
    if not addresses:
        raise ExplainerError("host could not be resolved")
    for addr_info in addresses:
        addr = addr_info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            raise ExplainerError("host resolved to an unparseable address")
        if not ip.is_global:
            raise ExplainerError("host resolves to a private or reserved address")


def _decode_body(raw: bytes, content_type: str) -> str:
    """Use the charset declared in Content-Type when Python knows it,
    otherwise UTF-8. Never raises: unknown codecs and undecodable bytes
    both fall back rather than propagate."""
    charset = "utf-8"
    if content_type and "charset=" in content_type.lower():
        declared = content_type.lower().split("charset=", 1)[1].split(";", 1)[0].strip().strip('"')
        try:
            codecs.lookup(declared)
            charset = declared
        except LookupError:
            charset = "utf-8"
    return raw.decode(charset, errors="replace")


def _close(response) -> None:
    close = getattr(response, "close", None)
    if close:
        close()


def _read_body(response) -> str:
    chunks = []
    total = 0
    try:
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > EXPLAINER_MAX_BYTES:
                raise ExplainerError("explainer file is too large")
            chunks.append(chunk)
    finally:
        _close(response)
    raw = b"".join(chunks)
    content_type = response.headers.get("content-type", "") if response.headers else ""
    return _decode_body(raw, content_type)


def http_get_text(url: str, get=requests.get, resolver=socket.getaddrinfo) -> str:
    """The production fetcher. Owns every network-facing check: https-only,
    host safety on every hop, manual redirect following with a hop cap, and
    the Google sign-in final-host check. Returns decoded text of a 2xx
    response; never returns a redirect body."""
    current_url = url
    redirects = 0
    while True:
        parsed = urlparse(current_url)
        if parsed.scheme != "https":
            raise ExplainerError("explainer links must use https")
        check_host(current_url, resolver)
        response = get(current_url, stream=True, timeout=60, allow_redirects=False)
        status = response.status_code
        if 300 <= status < 400:
            redirects += 1
            if redirects > MAX_REDIRECTS:
                _close(response)
                raise ExplainerError("too many redirects")
            location = response.headers.get("Location") or response.headers.get("location")
            _close(response)
            if not location:
                raise ExplainerError("redirect with no Location header")
            current_url = urljoin(current_url, location)
            continue
        if not (200 <= status < 300):
            _close(response)
            raise ExplainerError(f"explainer host returned status {status}")
        if parsed.hostname == "accounts.google.com":
            _close(response)
            raise ExplainerError(GOOGLE_SIGNIN_MESSAGE)
        return _read_body(response)


def fetch_explainer(url: str, fetch=http_get_text) -> str:
    if not url.lower().startswith("https://"):
        raise ExplainerError("explainer links must use https")
    body = fetch(download_url(url))
    if len(body.encode("utf-8")) > EXPLAINER_MAX_BYTES:
        raise ExplainerError("explainer file is too large")
    if "Virus scan warning" in body:
        raise ExplainerError(GOOGLE_VIRUS_SCAN_MESSAGE)
    if "Sign in - Google Accounts" in body:
        raise ExplainerError(GOOGLE_SIGNIN_MESSAGE)
    head = body[:2000].lower()
    if "<html" not in head and "<!doctype html" not in head:
        raise ExplainerError("explainer content is not HTML")
    return body


def store_explainer(root: Path, page_id: str, html: str) -> Path:
    if not PAGE_ID_PATTERN.fullmatch(page_id):
        raise ExplainerError("invalid page ID format")
    folder = root / "explainers" / page_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "explainer.txt"
    path.write_text(html, encoding="utf-8", newline="")
    return path
