"""Explainers are submitted content that executes. They are stored as text so
that no runnable copy exists on the site's origin, and the page runs them only
inside a sandboxed frame.

Network safety (host checks, redirect handling, the Google Drive interstitial's
final host) all lives in the fetcher, http_get_text. fetch_explainer only
inspects content that has already been fetched: size, whether it is HTML, and
the Drive interstitial body markers. A stub fetch passed into fetch_explainer
therefore does no DNS lookups at all, which is what keeps the tests offline.

The host that gets safety-checked must be, by construction, the host that
gets connected to. urllib.parse and the client library can disagree about
where the authority component ends (a backslash, or an IDNA host normalised
to its xn-- form only at request-prepare time), so every hop is checked using
the host urllib3 reads off the actually-prepared request, not a second,
independent parse of the URL text.
"""

import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import urllib3

from sync.config import EXPLAINER_MAX_BYTES

DRIVE_FILE = re.compile(r"drive\.google\.com/file/d/([^/]+)")
DRIVE_OPEN = re.compile(r"drive\.google\.com/open\?id=([^&]+)")
PAGE_ID_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}(?:-(?:[a-z]|\d+))?$")

MAX_REDIRECTS = 3

# A literal backslash. Written via chr() rather than a string escape: this
# source must stay ASCII-only, and a backslash is one of the characters this
# module explicitly refuses in a URL, so it earns a name rather than being
# typed inline.
BACKSLASH = chr(92)

GOOGLE_SIGNIN_MESSAGE = (
    "explainer link shows a Google sign-in page; "
    "set file sharing to 'anyone with the link'"
)
GOOGLE_VIRUS_SCAN_MESSAGE = (
    "explainer link shows Google's virus-scan warning page; "
    "the file may be too large for Drive to scan automatically"
)

_SESSION = requests.Session()


class ExplainerError(Exception):
    pass


def download_url(url: str) -> str:
    for pattern in (DRIVE_FILE, DRIVE_OPEN):
        match = pattern.search(url)
        if match:
            return f"https://drive.google.com/uc?export=download&id={match.group(1)}"
    return url


def check_host(url: str, resolver=socket.getaddrinfo) -> None:
    """Fail closed: block anything that is not a globally routable,
    non-multicast address, an address the resolver could not classify, or a
    host with no addresses at all."""
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise ExplainerError("invalid URL")
    _check_resolved_host(host, resolver)


def _check_resolved_host(host: str, resolver=socket.getaddrinfo) -> None:
    try:
        addresses = resolver(host, None)
    except (socket.gaierror, UnicodeError):
        # UnicodeError covers, among other things, a label over 63 octets:
        # getaddrinfo's IDNA validation rejects it locally, before any
        # lookup is attempted.
        raise ExplainerError("host could not be resolved")
    if not addresses:
        raise ExplainerError("host could not be resolved")
    for addr_info in addresses:
        addr = addr_info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            raise ExplainerError("host resolved to an unparseable address")
        if not ip.is_global or ip.is_multicast:
            raise ExplainerError("host resolves to a private or reserved address")


def _decode_body(raw: bytes, content_type: str) -> str:
    """Use the charset declared in Content-Type, otherwise UTF-8. Some
    codecs (base64, hex, zlib, bz2, rot13, uu, quopri) are registered names
    that bytes.decode() itself refuses with LookupError; others decode text
    only in the abstract (idna, undefined -> UnicodeError; punycode often
    -> UnicodeDecodeError on real content; an embedded NUL in the name
    -> ValueError). None of those are a reason to fail the fetch: fall back
    to UTF-8 with errors="replace", which cannot itself raise."""
    charset = "utf-8"
    if content_type and "charset=" in content_type.lower():
        declared = content_type.lower().split("charset=", 1)[1].split(";", 1)[0].strip().strip('"')
        if declared:
            charset = declared
    try:
        return raw.decode(charset, errors="replace")
    except (LookupError, UnicodeError, ValueError):
        return raw.decode("utf-8", errors="replace")


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


def _send(prepared, **kwargs):
    return _SESSION.send(prepared, **kwargs)


def _follow_and_fetch(url: str, resolver, send) -> str:
    current_url = url
    redirects = 0
    while True:
        if BACKSLASH in current_url:
            raise ExplainerError("explainer links may not contain a backslash")
        parsed = urlparse(current_url)
        if "@" in parsed.netloc:
            raise ExplainerError("explainer links may not include user info")
        if parsed.scheme != "https":
            raise ExplainerError("explainer links must use https")

        # Check the host urllib3 will actually dial, not a second,
        # independent parse of the URL text: build the request the way
        # requests itself will send it, and read the host off THAT.
        prepared = requests.Request("GET", current_url).prepare()
        host = urllib3.util.parse_url(prepared.url).host
        if not host:
            raise ExplainerError("invalid URL")
        _check_resolved_host(host, resolver)

        response = send(prepared, stream=True, timeout=60, allow_redirects=False)
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
        if host == "accounts.google.com":
            _close(response)
            raise ExplainerError(GOOGLE_SIGNIN_MESSAGE)
        return _read_body(response)


def http_get_text(url: str, resolver=socket.getaddrinfo, send=_send) -> str:
    """The production fetcher. Owns every network-facing check: link-shape
    rejection (backslash, embedded user info), https-only, host safety on
    every hop, manual redirect following with a hop cap, and the Google
    sign-in final-host check. Returns decoded text of a 2xx response; never
    returns a redirect body.

    Any failure -- ours or a lower library's (a malformed redirect target
    that urljoin rejects, a resolver that chokes on an oversized label, or
    anything similarly shaped) -- surfaces as ExplainerError. A later sync
    step catches only that type around this call, so anything else would
    abort every page's build over one hostile approved link."""
    try:
        return _follow_and_fetch(url, resolver, send)
    except ExplainerError:
        raise
    except Exception as exc:
        raise ExplainerError(f"explainer link could not be fetched: {exc}") from exc


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
