"""Explainers are submitted content that executes. They are stored as text so
that no runnable copy exists on the site's origin, and the page runs them only
inside a sandboxed frame.

Network safety (host checks, redirect handling, the Google Drive interstitial's
final host, the time budget) all lives in the fetcher, http_get_text.
fetch_explainer only inspects content that has already been fetched: size,
whether it is HTML, and the Drive interstitial body markers. A stub fetch
passed into fetch_explainer therefore does no DNS lookups at all, which is
what keeps the tests offline.

The host that gets safety-checked must be the host that gets connected to.
Every hop builds its request with requests.Request(...).prepare(), checks
urllib3.util.parse_url(prepared.url).host, and sends that same prepared
object. In requests 2.32 the adapter dials a different parse of the same
string: urllib.parse.urlparse(prepared.url).hostname. The two parsers agree
there only because requests' prepare_url has already normalised the URL
(IDNA-encoded the host, percent-encoded a backslash and control characters)
before either of them sees it. That normalisation, not a shared parser, is
what makes the checked host the dialled host, which is why a backslash or
user info in the link text is refused outright rather than left to it.
"""

import ipaddress
import re
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import urllib3

from sync.config import EXPLAINER_MAX_BYTES

DRIVE_FILE = re.compile(r"drive\.google\.com/file/d/([^/]+)")
DRIVE_OPEN = re.compile(r"drive\.google\.com/open\?id=([^&]+)")
PAGE_ID_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}(?:-(?:[a-z]|\d+))?$")

MAX_REDIRECTS = 3

# Wall-clock seconds for one whole download, across every hop and chunk. The
# 60-second read timeout bounds each socket read, not the download: a server
# sending one byte just inside it would otherwise hold the sync run forever.
FETCH_BUDGET_SECONDS = 120

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


def check_host(host: str, resolver=socket.getaddrinfo) -> None:
    """Fail closed: block anything that is not a globally routable,
    non-multicast address, an address the resolver could not classify, or a
    host with no addresses at all.

    Takes a host, never a URL. In production it is the host read off the
    prepared request (see the module docstring); parsing a URL here would
    bring back a second parser that can disagree with the one that dials."""
    if not host:
        # Windows getaddrinfo resolves "" to the machine's own addresses.
        raise ExplainerError("invalid URL")
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
        text = raw.decode(charset, errors="replace")
    except (LookupError, UnicodeError, ValueError):
        text = raw.decode("utf-8", errors="replace")
    return _without_surrogates(text)


def _without_surrogates(text: str) -> str:
    """Replace any lone surrogate with "?". Some codecs (utf-7,
    unicode_escape, raw_unicode_escape) decode without error into one, and a
    lone surrogate cannot be encoded as UTF-8: the size check and write_text
    would both raise UnicodeEncodeError, which the caller does not catch."""
    return text.encode("utf-8", "replace").decode("utf-8")


def _close(response) -> None:
    close = getattr(response, "close", None)
    if close:
        close()


def _check_budget(clock, deadline: float) -> None:
    if clock() > deadline:
        raise ExplainerError(
            f"explainer download took longer than {FETCH_BUDGET_SECONDS} seconds"
        )


def _read_body(response, clock, deadline: float) -> str:
    chunks = []
    total = 0
    try:
        for chunk in response.iter_content(chunk_size=65536):
            _check_budget(clock, deadline)
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
    # Straight to the adapter, not through Session.send. Even with
    # allow_redirects=False, Session.send calls resolve_redirects to fill
    # response._next, and that reads the whole 3xx body into memory with no
    # size cap. The adapter sends one request and follows nothing.
    return _SESSION.get_adapter(prepared.url).send(prepared, **kwargs)


def _follow_and_fetch(url: str, resolver, send, clock, deadline: float) -> str:
    current_url = url
    redirects = 0
    while True:
        _check_budget(clock, deadline)
        if BACKSLASH in current_url:
            raise ExplainerError("explainer links may not contain a backslash")
        parsed = urlparse(current_url)
        if "@" in parsed.netloc:
            raise ExplainerError("explainer links may not include user info")
        if parsed.scheme != "https":
            raise ExplainerError("explainer links must use https")

        # Check the host read off the request exactly as it will be sent, not
        # a second parse of the link text, and send that same object. The
        # module docstring says why this host is the one that gets dialled.
        prepared = requests.Request("GET", current_url).prepare()
        host = urllib3.util.parse_url(prepared.url).host
        check_host(host, resolver)

        response = send(prepared, stream=True, timeout=60)
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
        return _read_body(response, clock, deadline)


def _fetch_within_budget(url: str, resolver, send, clock) -> str:
    deadline = clock() + FETCH_BUDGET_SECONDS
    try:
        return _follow_and_fetch(url, resolver, send, clock, deadline)
    except ExplainerError:
        raise
    except Exception as exc:
        raise ExplainerError(
            f"explainer link could not be fetched: {type(exc).__name__}: {exc}"
        ) from exc


def http_get_text(
    url: str, resolver=socket.getaddrinfo, send=_send, clock=time.monotonic
) -> str:
    """The production fetcher. Owns every network-facing check: link-shape
    rejection (backslash, embedded user info), https-only, host safety on
    every hop, manual redirect following with a hop cap, the Google sign-in
    final-host check, and the time budget. Returns decoded text of a 2xx
    response; never reads a redirect body.

    The whole download gets FETCH_BUDGET_SECONDS of wall-clock time across
    every hop and chunk. `clock` is checked before every hop and on every
    chunk, which stops the download and closes the response. That check
    cannot run while one call is blocked, though: a read waits for its whole
    chunk or EOF, and each arriving byte resets the socket timeout, so a slow
    drip never reaches a chunk boundary. The fetch therefore runs on a daemon
    thread, and the caller stops waiting for it once the budget is spent. An
    abandoned thread holds at most one connection and one capped body, until
    its blocked call returns or the process exits.

    Any failure -- ours or a lower library's (a malformed redirect target
    that urljoin rejects, a resolver that chokes on an oversized label, or
    anything similarly shaped) -- surfaces as ExplainerError. A later sync
    step catches only that type around this call, so anything else would
    abort every page's build over one hostile approved link."""
    outcome = {}

    def fetch() -> None:
        try:
            outcome["text"] = _fetch_within_budget(url, resolver, send, clock)
        except BaseException as exc:
            outcome["error"] = exc

    worker = threading.Thread(target=fetch, name="explainer-fetch", daemon=True)
    worker.start()
    worker.join(FETCH_BUDGET_SECONDS)
    if worker.is_alive():
        raise ExplainerError(
            f"explainer download took longer than {FETCH_BUDGET_SECONDS} seconds"
        )
    if "error" in outcome:
        raise outcome["error"]
    return outcome["text"]


def fetch_explainer(url: str, fetch=http_get_text) -> str:
    if not url.lower().startswith("https://"):
        raise ExplainerError("explainer links must use https")
    # Cleaned here as well as in the decoder: a fetch other than
    # http_get_text skips the decoder entirely.
    body = _without_surrogates(fetch(download_url(url)))
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
