import threading
import time

import pytest
import requests
from requests.adapters import BaseAdapter
from requests.structures import CaseInsensitiveDict

from sync import explainers
from sync.explainers import (
    ExplainerError,
    check_host,
    download_url,
    fetch_explainer,
    http_get_text,
    store_explainer,
)

# Source must stay ASCII-only. Build the non-ASCII test values at runtime via
# chr() rather than an escape sequence in a string literal.
CAFE = "caf" + chr(0xE9)
BACKSLASH = chr(92)


class Streamed:
    """Base for a fake 2xx response. A subclass yields its body's bytes from
    chunks(); the fetcher reads them through raw.stream, as it reads the
    urllib3 raw stream of a real response."""

    @property
    def raw(self):
        test = self

        class Raw:
            def stream(self, amt=None, decode_content=None):
                assert decode_content is False, "the body must be read undecoded"
                yield from test.chunks()

        return Raw()


# --- The brief's original six, unchanged ---


def test_a_drive_share_link_becomes_a_download_link():
    share = "https://drive.google.com/file/d/ABC123/view?usp=sharing"
    assert download_url(share) == "https://drive.google.com/uc?export=download&id=ABC123"


def test_a_direct_link_is_left_alone():
    assert download_url("https://example.com/x.html") == "https://example.com/x.html"


def test_http_links_are_refused():
    with pytest.raises(ExplainerError, match="https"):
        fetch_explainer("http://example.com/x.html", lambda url: "<html></html>")


def test_content_that_is_not_html_is_refused():
    with pytest.raises(ExplainerError, match="HTML"):
        fetch_explainer("https://example.com/x", lambda url: "just some text")


def test_oversized_content_is_refused():
    big = "<html>" + "x" * 10_000_001
    with pytest.raises(ExplainerError, match="large"):
        fetch_explainer("https://example.com/x", lambda url: big)


def test_the_file_is_stored_as_text_not_as_html(tmp_path):
    path = store_explainer(tmp_path, "2026-10-07", "<html>hi</html>")
    assert path.name == "explainer.txt"
    assert path.read_text(encoding="utf-8") == "<html>hi</html>"
    assert not list(tmp_path.rglob("*.html"))


# --- Round 1 fixes that still hold ---


def test_stored_file_byte_length_matches_input(tmp_path):
    body = "<html>\nLine 2\nLine 3</html>"
    path = store_explainer(tmp_path, "2026-10-07", body)
    file_bytes = path.read_bytes()
    expected_bytes = body.encode("utf-8")
    assert len(file_bytes) == len(expected_bytes)
    assert file_bytes == expected_bytes


def test_private_ip_is_rejected():
    def fake_resolver(host, port):
        if host == "private.example":
            return [(2, 1, 6, "", ("192.168.1.1", 0))]
        return []

    with pytest.raises(ExplainerError, match="private or reserved"):
        check_host("private.example", fake_resolver)


def test_loopback_ip_is_rejected():
    def fake_resolver(host, port):
        if host == "localhost":
            return [(2, 1, 6, "", ("127.0.0.1", 0))]
        return []

    with pytest.raises(ExplainerError, match="private or reserved"):
        check_host("localhost", fake_resolver)


def test_metadata_ip_is_rejected():
    def fake_resolver(host, port):
        if host == "metadata.example":
            return [(2, 1, 6, "", ("169.254.169.254", 0))]
        return []

    with pytest.raises(ExplainerError, match="private or reserved"):
        check_host("metadata.example", fake_resolver)


def test_public_ip_is_allowed():
    def fake_resolver(host, port):
        if host == "public.example":
            return [(2, 1, 6, "", ("8.8.8.8", 0))]
        return []

    check_host("public.example", fake_resolver)


def test_page_id_must_match_date_format():
    with pytest.raises(ExplainerError, match="invalid page ID"):
        store_explainer(None, "../../escaped", "<html></html>")


def test_valid_page_ids_are_accepted(tmp_path):
    valid_ids = ["2026-10-07", "2026-10-07-a", "2026-10-07-2"]
    for page_id in valid_ids:
        path = store_explainer(tmp_path, page_id, "<html>test</html>")
        assert path.parent.name == page_id


def test_page_id_rejects_a_trailing_newline(tmp_path):
    # re.match plus a trailing "$" accepts "id\n"; only fullmatch closes that.
    with pytest.raises(ExplainerError, match="invalid page ID"):
        store_explainer(tmp_path, "2026-10-07\n", "<html></html>")


# --- Round 1 tests rewritten for the round 2 fetch_explainer / http_get_text split ---
#
# fetch_explainer no longer takes a resolver: host safety moved entirely into
# http_get_text, so these now call fetch_explainer with only a stub `fetch`
# that returns a body directly, doing no network work at all.


def test_google_virus_scan_warning_is_rejected():
    def fake_fetch(url):
        return "<html><body>Virus scan warning</body></html>"

    with pytest.raises(ExplainerError, match="virus"):
        fetch_explainer("https://drive.google.com/test", fake_fetch)


def test_google_accounts_signin_text_is_rejected():
    def fake_fetch(url):
        return "<html><body>Sign in - Google Accounts page</body></html>"

    with pytest.raises(ExplainerError, match="sign-in"):
        fetch_explainer("https://drive.google.com/test", fake_fetch)


# --- check_host: fail-closed cases ---


def test_check_host_blocks_shared_address_space():
    # 100.64.0.0/10 (CGNAT) is not private/loopback/link-local/reserved/
    # multicast under the old enumerated flags, but it is not is_global either.
    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("100.64.0.1", 0))]

    with pytest.raises(ExplainerError, match="private or reserved"):
        check_host("cgnat.example", fake_resolver)


def test_check_host_blocks_an_empty_resolver_result():
    def fake_resolver(host, port):
        return []

    with pytest.raises(ExplainerError, match="could not be resolved"):
        check_host("ghost.example", fake_resolver)


def test_check_host_blocks_an_empty_host():
    # Windows getaddrinfo resolves "" to the machine's own addresses, so an
    # empty host must be refused before the resolver is asked.
    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with pytest.raises(ExplainerError, match="invalid URL"):
        check_host("", fake_resolver)


def test_check_host_blocks_multicast_addresses():
    # 224.0.0.1's is_global is True in Python's ipaddress module (multicast
    # is not classified as private/reserved), so is_global alone lets it
    # through; is_multicast must be checked separately.
    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("224.0.0.1", 0))]

    with pytest.raises(ExplainerError, match="private or reserved"):
        check_host("multicast.example", fake_resolver)


def test_a_too_long_host_label_is_rejected_as_an_explainer_error():
    # getaddrinfo's own IDNA validation rejects a label over 63 octets with
    # UnicodeError, entirely locally: no network lookup is attempted, so this
    # is safe to run against the real default resolver.
    long_host = "a" * 64 + ".example.com"

    def fake_send(prepared, stream, timeout):
        raise AssertionError("send must not be called: the host check must reject first")

    with pytest.raises(ExplainerError, match="could not be resolved"):
        http_get_text(f"https://{long_host}/x", send=fake_send)


# --- http_get_text: the production fetcher, redirects, hosts, encoding ---
#
# Every test here injects both `resolver` and `send`; none touches the
# network. `send` receives the actually-prepared request (requests.Request
# (...).prepare() runs for real -- it is pure local URL/header construction,
# no I/O), so stubs key off `prepared.url` rather than a raw url argument.


def test_a_redirect_to_a_public_host_is_followed():
    class RedirectResponse:
        status_code = 303
        headers = {"Location": "https://cdn.example/final.html"}

        def close(self):
            pass

    class FinalResponse(Streamed):
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}

        def chunks(self):
            yield b"<html>final</html>"

        def close(self):
            pass

    calls = []

    def fake_send(prepared, stream, timeout):
        calls.append(prepared.url)
        if prepared.url == "https://start.example/x":
            return RedirectResponse()
        return FinalResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    result = http_get_text("https://start.example/x", fake_resolver, fake_send)
    assert result == "<html>final</html>"
    assert calls == ["https://start.example/x", "https://cdn.example/final.html"]


def test_a_relative_redirect_location_is_resolved_against_the_current_url():
    class RedirectResponse:
        status_code = 302
        headers = {"Location": "/final.html"}

        def close(self):
            pass

    class FinalResponse(Streamed):
        status_code = 200
        headers = {"content-type": "text/html"}

        def chunks(self):
            yield b"<html>ok</html>"

        def close(self):
            pass

    def fake_send(prepared, stream, timeout):
        if prepared.url == "https://start.example/dir/x":
            return RedirectResponse()
        assert prepared.url == "https://start.example/final.html"
        return FinalResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    result = http_get_text("https://start.example/dir/x", fake_resolver, fake_send)
    assert result == "<html>ok</html>"


def test_a_redirect_to_a_metadata_address_is_rejected_before_the_hop_is_fetched():
    class RedirectResponse:
        status_code = 302
        headers = {"Location": "https://metadata.example/secret"}

        def close(self):
            pass

    calls = []

    def fake_send(prepared, stream, timeout):
        calls.append(prepared.url)
        return RedirectResponse()

    def fake_resolver(host, port):
        if host == "metadata.example":
            return [(2, 1, 6, "", ("169.254.169.254", 0))]
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with pytest.raises(ExplainerError, match="private or reserved"):
        http_get_text("https://start.example/x", fake_resolver, fake_send)
    assert calls == ["https://start.example/x"]


def test_a_redirect_to_an_http_url_is_rejected():
    class RedirectResponse:
        status_code = 302
        headers = {"Location": "http://insecure.example/x"}

        def close(self):
            pass

    def fake_send(prepared, stream, timeout):
        return RedirectResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with pytest.raises(ExplainerError, match="https"):
        http_get_text("https://start.example/x", fake_resolver, fake_send)


def test_a_fourth_redirect_is_rejected():
    urls = [
        "https://start.example/1",
        "https://start.example/2",
        "https://start.example/3",
        "https://start.example/4",
        "https://start.example/5",
    ]

    class RedirectResponse:
        status_code = 302

        def __init__(self, location):
            self.headers = {"Location": location}

        def close(self):
            pass

    def fake_send(prepared, stream, timeout):
        idx = urls.index(prepared.url)
        return RedirectResponse(urls[idx + 1])

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with pytest.raises(ExplainerError, match="too many redirects"):
        http_get_text(urls[0], fake_resolver, fake_send)


def test_exactly_three_redirects_then_success_is_allowed():
    # Pins the cap at three: a regression that quietly tightened it to two
    # would only show up here, not in the fourth-redirect test above.
    urls = [
        "https://start.example/1",
        "https://start.example/2",
        "https://start.example/3",
        "https://start.example/4",
    ]

    class RedirectResponse:
        status_code = 302

        def __init__(self, location):
            self.headers = {"Location": location}

        def close(self):
            pass

    class FinalResponse(Streamed):
        status_code = 200
        headers = {"content-type": "text/html"}

        def chunks(self):
            yield b"<html>done</html>"

        def close(self):
            pass

    def fake_send(prepared, stream, timeout):
        idx = urls.index(prepared.url)
        if idx < len(urls) - 1:
            return RedirectResponse(urls[idx + 1])
        return FinalResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    result = http_get_text(urls[0], fake_resolver, fake_send)
    assert result == "<html>done</html>"


def test_a_drive_link_redirecting_to_google_signin_is_rejected():
    # The final-host check has to see the host actually reached after
    # following redirects, not the submitted URL: a Drive download link
    # commonly redirects to accounts.google.com when sharing is not public.
    class RedirectResponse:
        status_code = 302
        headers = {"Location": "https://accounts.google.com/signin?continue=x"}

        def close(self):
            pass

    class FinalResponse(Streamed):
        status_code = 200
        headers = {"content-type": "text/html"}

        def chunks(self):
            yield b"<html>Sign in</html>"

        def close(self):
            pass

    def fake_send(prepared, stream, timeout):
        if prepared.url.startswith("https://drive.google.com"):
            return RedirectResponse()
        return FinalResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("142.251.32.14", 0))]

    with pytest.raises(ExplainerError, match="sign-in"):
        http_get_text(
            "https://drive.google.com/uc?export=download&id=ABC123",
            fake_resolver,
            fake_send,
        )


def test_non_2xx_final_status_is_rejected():
    class ErrorResponse:
        status_code = 404
        headers = {}

        def close(self):
            pass

    def fake_send(prepared, stream, timeout):
        return ErrorResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with pytest.raises(ExplainerError, match="404"):
        http_get_text("https://start.example/missing", fake_resolver, fake_send)


def test_streaming_stops_when_size_exceeded():
    chunks = ["<html>", "x" * 65536, "x" * 65536, "x" * 65536, "x" * 10_000_001]
    chunk_iter = iter(chunks)

    class FinalResponse(Streamed):
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}

        def chunks(self):
            for chunk in chunk_iter:
                yield chunk.encode("utf-8") if isinstance(chunk, str) else chunk

        def close(self):
            pass

    def fake_send(prepared, stream, timeout):
        return FinalResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with pytest.raises(ExplainerError, match="large"):
        http_get_text("https://start.example/big", fake_resolver, fake_send)


# --- Link-shape rejection: the host you check must be the host you connect to ---


def test_a_redirect_location_with_a_backslash_is_rejected_before_the_hop_is_fetched():
    # urllib.parse reads the text after "@" as the host here, but requests
    # (through urllib3) connects to the address before the backslash. Refuse
    # the shape outright rather than rely on parser agreement.
    location = "https://169.254.169.254" + BACKSLASH + "@public.example/"

    class RedirectResponse:
        status_code = 302
        headers = {"Location": location}

        def close(self):
            pass

    calls = []

    def fake_send(prepared, stream, timeout):
        calls.append(prepared.url)
        return RedirectResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with pytest.raises(ExplainerError, match="backslash"):
        http_get_text("https://start.example/x", fake_resolver, fake_send)
    assert calls == ["https://start.example/x"]


def test_a_redirect_location_with_user_info_is_rejected():
    class RedirectResponse:
        status_code = 302
        headers = {"Location": "https://user@host.example/path"}

        def close(self):
            pass

    def fake_send(prepared, stream, timeout):
        return RedirectResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with pytest.raises(ExplainerError, match="user info"):
        http_get_text("https://start.example/x", fake_resolver, fake_send)


def test_an_idna_host_is_checked_by_its_punycode_form():
    # urlparse().hostname would return the raw label here; requests encodes
    # it to xn--strae-oqa.example before connecting. The resolver must see
    # the same form requests will actually dial.
    seen_hosts = []

    def fake_resolver(host, port):
        seen_hosts.append(host)
        return [(2, 1, 6, "", ("10.0.0.1", 0))]  # private: must be rejected

    def fake_send(prepared, stream, timeout):
        raise AssertionError("send must not be called: the host check must reject first")

    url = "https://stra" + chr(0xDF) + "e.example/"

    with pytest.raises(ExplainerError, match="private or reserved"):
        http_get_text(url, fake_resolver, fake_send)
    assert len(seen_hosts) == 1
    assert seen_hosts[0].startswith("xn--")


def test_a_malformed_redirect_target_is_rejected_as_an_explainer_error():
    # urljoin raises ValueError on this malformed IPv6-looking target; any
    # such parse failure must still surface as ExplainerError, since a later
    # sync step catches only that type.
    class RedirectResponse:
        status_code = 302
        headers = {"Location": "https://[169.254/x"}

        def close(self):
            pass

    def fake_send(prepared, stream, timeout):
        return RedirectResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with pytest.raises(ExplainerError, match="could not be fetched"):
        http_get_text("https://start.example/x", fake_resolver, fake_send)


# --- Decoding: never raise anything but the caller's own errors ---


def test_declared_charset_used_when_present_otherwise_utf8():
    # requests defaults response.encoding to ISO-8859-1 when no charset is
    # declared for a text/* body; our own decoding must not trust that
    # default. The body is UTF-8 bytes for CAFE ("caf" + e-acute). If the
    # UTF-8 fallback in _decode_body were removed, this would decode as
    # ISO-8859-1 and fail the assertion.
    class FinalResponse(Streamed):
        status_code = 200
        headers = {"content-type": "text/html"}
        encoding = "ISO-8859-1"

        def chunks(self):
            yield CAFE.encode("utf-8")

        def close(self):
            pass

    def fake_send(prepared, stream, timeout):
        return FinalResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    result = http_get_text("https://start.example/accent", fake_resolver, fake_send)
    assert result == CAFE


def test_an_unknown_declared_charset_falls_back_to_utf8_instead_of_raising():
    class FinalResponse(Streamed):
        status_code = 200
        headers = {"content-type": "text/html; charset=bogus"}

        def chunks(self):
            yield CAFE.encode("utf-8")

        def close(self):
            pass

    def fake_send(prepared, stream, timeout):
        return FinalResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    result = http_get_text("https://start.example/bogus-charset", fake_resolver, fake_send)
    assert result == CAFE


def test_an_invalid_utf8_byte_is_replaced_instead_of_raising():
    class FinalResponse(Streamed):
        status_code = 200
        headers = {"content-type": "text/html"}

        def chunks(self):
            yield b"<html>\xff\xfe broken</html>"

        def close(self):
            pass

    def fake_send(prepared, stream, timeout):
        return FinalResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    result = http_get_text("https://start.example/badbytes", fake_resolver, fake_send)
    assert "<html>" in result
    assert "broken</html>" in result


def test_a_base64_declared_charset_falls_back_to_utf8():
    # codecs.lookup("base64") would succeed; bytes.decode("base64") itself
    # raises LookupError ("not a text encoding"). The fallback must catch
    # that, not just an unrecognised name.
    class FinalResponse(Streamed):
        status_code = 200
        headers = {"content-type": "text/html; charset=base64"}

        def chunks(self):
            yield CAFE.encode("utf-8")

        def close(self):
            pass

    def fake_send(prepared, stream, timeout):
        return FinalResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    result = http_get_text("https://start.example/base64-charset", fake_resolver, fake_send)
    assert result == CAFE


def test_an_idna_declared_charset_falls_back_to_utf8():
    # bytes.decode("idna") raises UnicodeError ("unsupported error handling
    # replace"), not LookupError.
    class FinalResponse(Streamed):
        status_code = 200
        headers = {"content-type": "text/html; charset=idna"}

        def chunks(self):
            yield CAFE.encode("utf-8")

        def close(self):
            pass

    def fake_send(prepared, stream, timeout):
        return FinalResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    result = http_get_text("https://start.example/idna-charset", fake_resolver, fake_send)
    assert result == CAFE


def test_a_punycode_declared_charset_falls_back_to_utf8():
    # bytes.decode("punycode") ASCII-decodes internally before the bootstring
    # step; any non-ASCII byte (CAFE's UTF-8 form has one) raises
    # UnicodeDecodeError.
    class FinalResponse(Streamed):
        status_code = 200
        headers = {"content-type": "text/html; charset=punycode"}

        def chunks(self):
            yield CAFE.encode("utf-8")

        def close(self):
            pass

    def fake_send(prepared, stream, timeout):
        return FinalResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    result = http_get_text("https://start.example/punycode-charset", fake_resolver, fake_send)
    assert result == CAFE


def test_a_nul_byte_in_the_declared_charset_falls_back_to_utf8():
    class FinalResponse(Streamed):
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8" + chr(0)}

        def chunks(self):
            yield CAFE.encode("utf-8")

        def close(self):
            pass

    def fake_send(prepared, stream, timeout):
        return FinalResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    result = http_get_text("https://start.example/nul-charset", fake_resolver, fake_send)
    assert result == CAFE


# --- Round 4: one hostile link must not stall or crash the whole sync run ---


@pytest.mark.parametrize(
    "charset, body",
    [
        ("utf-7", b"<html>+2AA-</html>"),
        ("unicode_escape", ("<html>" + BACKSLASH + "ud800</html>").encode("ascii")),
        ("raw_unicode_escape", ("<html>" + BACKSLASH + "ud800</html>").encode("ascii")),
    ],
)
def test_a_charset_that_decodes_to_a_lone_surrogate_does_not_escape(tmp_path, charset, body):
    # These codecs decode without error into a lone surrogate, which then
    # raises UnicodeEncodeError on the size check and on write_text. The
    # caller catches only ExplainerError, so the text must come back clean.
    class FinalResponse(Streamed):
        status_code = 200
        headers = {"content-type": "text/html; charset=" + charset}

        def chunks(self):
            yield body

        def close(self):
            pass

    def fake_send(prepared, stream, timeout):
        return FinalResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    def fetch(url):
        return http_get_text(url, fake_resolver, fake_send)

    # The decoder's own output must be clean, not just fetch_explainer's.
    fetch("https://start.example/surrogate").encode("utf-8")
    result = fetch_explainer("https://start.example/surrogate", fetch)
    assert "<html>" in result
    result.encode("utf-8")
    store_explainer(tmp_path, "2026-10-07", result)


def test_a_fetch_returning_a_lone_surrogate_does_not_escape(tmp_path):
    # A stub fetch skips the decoder, so fetch_explainer must clean the text
    # itself rather than rely on http_get_text having done it.
    result = fetch_explainer(
        "https://start.example/x", lambda url: "<html>" + chr(0xD800) + "</html>"
    )
    assert "<html>" in result
    result.encode("utf-8")
    store_explainer(tmp_path, "2026-10-07", result)


def test_a_redirect_body_is_never_read(monkeypatch):
    # requests' Session.send, even with allow_redirects=False, calls
    # resolve_redirects(yield_requests=True) to fill response._next, and that
    # reads the whole 3xx body into memory with no size cap. This drives the
    # real production send through a stub adapter on a fresh session.
    class UnreadableBody:
        def __init__(self):
            self.reads = 0

        def read(self, *args, **kwargs):
            self.reads += 1
            raise AssertionError("a 3xx body must never be read")

        def close(self):
            pass

    class FinalBody:
        def __init__(self):
            self.data = b"<html>final</html>"

        def read(self, *args, **kwargs):
            out, self.data = self.data, b""
            return out

        def stream(self, amt=None, decode_content=None):
            assert decode_content is False
            yield self.read()

        def close(self):
            pass

    def make_response(prepared, status, headers, raw):
        response = requests.Response()
        response.status_code = status
        response.headers = CaseInsensitiveDict(headers)
        response.raw = raw
        response.url = prepared.url
        response.request = prepared
        return response

    redirect_body = UnreadableBody()
    received = []

    class StubAdapter(BaseAdapter):
        def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
            received.append((request, stream, timeout))
            if request.url == "https://start.example/x":
                headers = {"Location": "https://cdn.example/final.html"}
                return make_response(request, 302, headers, redirect_body)
            return make_response(request, 200, {"content-type": "text/html"}, FinalBody())

        def close(self):
            pass

    prepared_objects = []
    real_prepare = requests.Request.prepare

    def spy_prepare(self):
        prepared = real_prepare(self)
        prepared_objects.append(prepared)
        return prepared

    monkeypatch.setattr(requests.Request, "prepare", spy_prepare)
    session = requests.Session()
    session.mount("https://", StubAdapter())
    monkeypatch.setattr(explainers, "_SESSION", session)

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    result = http_get_text("https://start.example/x", fake_resolver)
    assert result == "<html>final</html>"
    assert redirect_body.reads == 0
    # Each hop sends the very object whose host was checked, streamed.
    assert len(received) == 2
    for (sent, stream, timeout), prepared in zip(received, prepared_objects):
        assert sent is prepared
        assert stream is True
        assert timeout == 60


def test_the_time_budget_is_checked_on_every_chunk():
    now = [1000.0]

    class SlowResponse(Streamed):
        status_code = 200
        headers = {"content-type": "text/html"}

        def __init__(self):
            self.closed = False

        def chunks(self):
            yield b"<html>"
            now[0] += 121
            yield b"late"
            raise AssertionError("reading must stop once the budget is spent")

        def close(self):
            self.closed = True

    response = SlowResponse()

    def fake_send(prepared, stream, timeout):
        return response

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with pytest.raises(ExplainerError, match="took longer than"):
        http_get_text(
            "https://start.example/slow", fake_resolver, fake_send, clock=lambda: now[0]
        )
    assert response.closed


def test_the_time_budget_spans_every_redirect_hop():
    # Each hop alone is well inside the budget; together they are not. The
    # third hop must not be sent.
    now = [1000.0]
    calls = []

    class RedirectResponse:
        status_code = 302

        def __init__(self, location):
            self.headers = {"Location": location}

        def close(self):
            pass

    def fake_send(prepared, stream, timeout):
        calls.append(prepared.url)
        now[0] += 70
        return RedirectResponse(f"https://start.example/{len(calls) + 1}")

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with pytest.raises(ExplainerError, match="took longer than"):
        http_get_text(
            "https://start.example/1", fake_resolver, fake_send, clock=lambda: now[0]
        )
    assert calls == ["https://start.example/1", "https://start.example/2"]


def test_a_call_that_blocks_past_the_budget_is_abandoned(monkeypatch):
    # A single read blocks until its whole chunk or EOF arrives, and each
    # arriving byte resets the socket timeout, so a slow drip gives the
    # per-chunk check no chunk boundary to run at. The caller must still get
    # an ExplainerError once the budget is spent.
    monkeypatch.setattr(explainers, "FETCH_BUDGET_SECONDS", 0.2)
    release = threading.Event()

    def fake_send(prepared, stream, timeout):
        release.wait(10)
        raise AssertionError("released after the test finished")

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    started = time.monotonic()
    try:
        with pytest.raises(ExplainerError, match="took longer than"):
            http_get_text("https://start.example/stuck", fake_resolver, fake_send)
    finally:
        release.set()
    assert time.monotonic() - started < 5


def test_a_wrapped_failure_keeps_its_cause_and_names_its_type():
    # MemoryError has an empty message, so without the type name the logged
    # reason would be blank.
    original = MemoryError()

    def fake_send(prepared, stream, timeout):
        raise original

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with pytest.raises(ExplainerError, match="MemoryError") as caught:
        http_get_text("https://start.example/x", fake_resolver, fake_send)
    assert caught.value.__cause__ is original


# --- Final review F1: a compressed body is refused, and never decoded ---
#
# requests' iter_content always decodes gzip, deflate and br, so a hostile
# host's small compressed body could expand past any cap before one chunk
# came back. The fetcher asks for identity, refuses any other encoding before
# reading, and reads the raw stream with decoding off.


def public_resolver(host, port):
    return [(2, 1, 6, "", ("8.8.8.8", 0))]


class RawBody:
    """A fake urllib3 raw stream that records how it was asked for bytes."""

    def __init__(self, *chunks):
        self.chunks = chunks
        self.calls = []

    def stream(self, amt=None, decode_content=None):
        self.calls.append((amt, decode_content))
        yield from self.chunks


class Tripwire:
    def stream(self, *args, **kwargs):
        raise AssertionError("a compressed body must never be read")


def fetch_one(response):
    return http_get_text("https://start.example/x", public_resolver,
                         lambda prepared, stream, timeout: response)


@pytest.mark.parametrize("name", ["Content-Encoding", "content-encoding"])
@pytest.mark.parametrize("value", ["gzip", " GZIP ", "br", "deflate", "gzip, identity"])
def test_a_compressed_response_is_refused_without_reading_its_body(name, value):
    class Compressed:
        status_code = 200
        headers = {"content-type": "text/html", name: value}
        raw = Tripwire()
        closed = False

        def close(self):
            Compressed.closed = True

    with pytest.raises(ExplainerError, match="compressed"):
        fetch_one(Compressed())
    assert Compressed.closed


def test_the_body_is_read_raw_with_decoding_off():
    class Final:
        status_code = 200
        headers = {"content-type": "text/html"}
        raw = RawBody(b"<html>ok</html>")

        def close(self):
            pass

    assert fetch_one(Final()) == "<html>ok</html>"
    assert Final.raw.calls == [(65536, False)]


def test_every_hop_asks_for_an_uncompressed_body():
    class Redirect:
        status_code = 302
        headers = {"Location": "https://cdn.example/final.html"}

        def close(self):
            pass

    class Final:
        status_code = 200
        headers = {"content-type": "text/html"}
        raw = RawBody(b"<html>ok</html>")

        def close(self):
            pass

    asked = []

    def fake_send(prepared, stream, timeout):
        asked.append(prepared.headers.get("Accept-Encoding"))
        return Redirect() if len(asked) == 1 else Final()

    assert http_get_text("https://start.example/x", public_resolver, fake_send) == "<html>ok</html>"
    assert asked == ["identity", "identity"]


@pytest.mark.parametrize("headers", [
    {"content-type": "text/html", "Content-Encoding": "identity"},
    {"content-type": "text/html", "content-encoding": " Identity "},
    {"content-type": "text/html", "Content-Encoding": ""},
    {"content-type": "text/html"},
], ids=["identity", "identity, spaced", "empty", "absent"])
def test_an_uncompressed_response_is_still_accepted(headers):
    class Final:
        status_code = 200
        raw = RawBody(b"<html>ok</html>")

        def close(self):
            pass

    Final.headers = headers
    assert fetch_one(Final()) == "<html>ok</html>"


def test_a_real_gzip_bomb_is_refused_through_the_production_send(monkeypatch):
    # Real requests and urllib3 objects this time: 5 MB of HTML-looking
    # bytes gzip to a few kilobytes. The body must be refused unread.
    import gzip
    import io

    import urllib3

    class Wire(io.BytesIO):
        taken = 0

        def read(self, *args):
            data = super().read(*args)
            Wire.taken += len(data)
            return data

        def readinto(self, buffer):
            count = super().readinto(buffer)
            Wire.taken += count
            return count

    wire = Wire(gzip.compress(b"<html>" + b" " * 5_000_000))

    class StubAdapter(BaseAdapter):
        def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
            response = requests.Response()
            response.status_code = 200
            response.headers = CaseInsensitiveDict({"Content-Type": "text/html",
                                                    "Content-Encoding": "gzip"})
            response.raw = urllib3.HTTPResponse(body=wire, headers=response.headers,
                                                preload_content=False)
            response.url = request.url
            response.request = request
            return response

        def close(self):
            pass

    session = requests.Session()
    session.mount("https://", StubAdapter())
    monkeypatch.setattr(explainers, "_SESSION", session)
    with pytest.raises(ExplainerError, match="compressed"):
        http_get_text("https://start.example/bomb", public_resolver)
    assert Wire.taken == 0
    assert wire.closed
