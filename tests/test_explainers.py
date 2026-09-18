import pytest
from sync.explainers import (
    ExplainerError,
    check_host,
    download_url,
    fetch_explainer,
    http_get_text,
    store_explainer,
)

# Source must stay ASCII-only. Build the one non-ASCII test string at
# runtime via chr() rather than an escape sequence in a string literal.
CAFE = "caf" + chr(0xE9)


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
        check_host("https://private.example/test", fake_resolver)


def test_loopback_ip_is_rejected():
    def fake_resolver(host, port):
        if host == "localhost":
            return [(2, 1, 6, "", ("127.0.0.1", 0))]
        return []

    with pytest.raises(ExplainerError, match="private or reserved"):
        check_host("https://localhost/test", fake_resolver)


def test_metadata_ip_is_rejected():
    def fake_resolver(host, port):
        if host == "metadata.example":
            return [(2, 1, 6, "", ("169.254.169.254", 0))]
        return []

    with pytest.raises(ExplainerError, match="private or reserved"):
        check_host("https://metadata.example/test", fake_resolver)


def test_public_ip_is_allowed():
    def fake_resolver(host, port):
        if host == "public.example":
            return [(2, 1, 6, "", ("8.8.8.8", 0))]
        return []

    check_host("https://public.example/test", fake_resolver)


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


# --- Round 1 tests rewritten for the new fetch_explainer / http_get_text split ---
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


# --- check_host: fail-closed cases the round 2 review added ---


def test_check_host_blocks_shared_address_space():
    # 100.64.0.0/10 (CGNAT) is not private/loopback/link-local/reserved/
    # multicast under the old enumerated flags, but it is not is_global either.
    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("100.64.0.1", 0))]

    with pytest.raises(ExplainerError, match="private or reserved"):
        check_host("https://cgnat.example/test", fake_resolver)


def test_check_host_blocks_an_empty_resolver_result():
    def fake_resolver(host, port):
        return []

    with pytest.raises(ExplainerError, match="could not be resolved"):
        check_host("https://ghost.example/test", fake_resolver)


# --- http_get_text: the production fetcher, redirects, hosts, encoding ---
#
# Every test here injects both `get` and `resolver`; none touches the network.


def test_a_redirect_to_a_public_host_is_followed():
    class RedirectResponse:
        status_code = 303
        headers = {"Location": "https://cdn.example/final.html"}

        def close(self):
            pass

    class FinalResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}

        def iter_content(self, chunk_size):
            yield b"<html>final</html>"

        def close(self):
            pass

    calls = []

    def fake_get(url, stream, timeout, allow_redirects):
        calls.append(url)
        if url == "https://start.example/x":
            return RedirectResponse()
        return FinalResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    result = http_get_text("https://start.example/x", fake_get, fake_resolver)
    assert result == "<html>final</html>"
    assert calls == ["https://start.example/x", "https://cdn.example/final.html"]


def test_a_relative_redirect_location_is_resolved_against_the_current_url():
    class RedirectResponse:
        status_code = 302
        headers = {"Location": "/final.html"}

        def close(self):
            pass

    class FinalResponse:
        status_code = 200
        headers = {"content-type": "text/html"}

        def iter_content(self, chunk_size):
            yield b"<html>ok</html>"

        def close(self):
            pass

    def fake_get(url, stream, timeout, allow_redirects):
        if url == "https://start.example/dir/x":
            return RedirectResponse()
        assert url == "https://start.example/final.html"
        return FinalResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    result = http_get_text("https://start.example/dir/x", fake_get, fake_resolver)
    assert result == "<html>ok</html>"


def test_a_redirect_to_a_metadata_address_is_rejected_before_the_hop_is_fetched():
    class RedirectResponse:
        status_code = 302
        headers = {"Location": "https://metadata.example/secret"}

        def close(self):
            pass

    calls = []

    def fake_get(url, stream, timeout, allow_redirects):
        calls.append(url)
        return RedirectResponse()

    def fake_resolver(host, port):
        if host == "metadata.example":
            return [(2, 1, 6, "", ("169.254.169.254", 0))]
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with pytest.raises(ExplainerError, match="private or reserved"):
        http_get_text("https://start.example/x", fake_get, fake_resolver)
    assert calls == ["https://start.example/x"]


def test_a_redirect_to_an_http_url_is_rejected():
    class RedirectResponse:
        status_code = 302
        headers = {"Location": "http://insecure.example/x"}

        def close(self):
            pass

    def fake_get(url, stream, timeout, allow_redirects):
        return RedirectResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with pytest.raises(ExplainerError, match="https"):
        http_get_text("https://start.example/x", fake_get, fake_resolver)


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

    def fake_get(url, stream, timeout, allow_redirects):
        idx = urls.index(url)
        return RedirectResponse(urls[idx + 1])

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with pytest.raises(ExplainerError, match="too many redirects"):
        http_get_text(urls[0], fake_get, fake_resolver)


def test_a_final_host_of_accounts_google_com_is_rejected():
    class FinalResponse:
        status_code = 200
        headers = {"content-type": "text/html"}

        def iter_content(self, chunk_size):
            yield b"<html>Sign in</html>"

        def close(self):
            pass

    def fake_get(url, stream, timeout, allow_redirects):
        return FinalResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("142.251.32.14", 0))]

    with pytest.raises(ExplainerError, match="sign-in"):
        http_get_text("https://accounts.google.com/signin", fake_get, fake_resolver)


def test_non_2xx_final_status_is_rejected():
    class ErrorResponse:
        status_code = 404
        headers = {}

        def close(self):
            pass

    def fake_get(url, stream, timeout, allow_redirects):
        return ErrorResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with pytest.raises(ExplainerError, match="404"):
        http_get_text("https://start.example/missing", fake_get, fake_resolver)


def test_streaming_stops_when_size_exceeded():
    chunks = ["<html>", "x" * 65536, "x" * 65536, "x" * 65536, "x" * 10_000_001]
    chunk_iter = iter(chunks)

    class FinalResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}

        def iter_content(self, chunk_size):
            for chunk in chunk_iter:
                yield chunk.encode("utf-8") if isinstance(chunk, str) else chunk

        def close(self):
            pass

    def fake_get(url, stream, timeout, allow_redirects):
        return FinalResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with pytest.raises(ExplainerError, match="large"):
        http_get_text("https://start.example/big", fake_get, fake_resolver)


def test_declared_charset_used_when_present_otherwise_utf8():
    # requests defaults response.encoding to ISO-8859-1 when no charset is
    # declared for a text/* body; our own decoding must not trust that
    # default. The body is UTF-8 bytes for CAFE ("caf" + e-acute). If the
    # UTF-8 fallback in _decode_body were removed, this would decode as
    # ISO-8859-1 and fail the assertion.
    class FinalResponse:
        status_code = 200
        headers = {"content-type": "text/html"}
        encoding = "ISO-8859-1"

        def iter_content(self, chunk_size):
            yield CAFE.encode("utf-8")

        def close(self):
            pass

    def fake_get(url, stream, timeout, allow_redirects):
        return FinalResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    result = http_get_text("https://start.example/accent", fake_get, fake_resolver)
    assert result == CAFE


def test_an_unknown_declared_charset_falls_back_to_utf8_instead_of_raising():
    class FinalResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=bogus"}

        def iter_content(self, chunk_size):
            yield CAFE.encode("utf-8")

        def close(self):
            pass

    def fake_get(url, stream, timeout, allow_redirects):
        return FinalResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    result = http_get_text("https://start.example/bogus-charset", fake_get, fake_resolver)
    assert result == CAFE


def test_an_invalid_utf8_byte_is_replaced_instead_of_raising():
    class FinalResponse:
        status_code = 200
        headers = {"content-type": "text/html"}

        def iter_content(self, chunk_size):
            yield b"<html>\xff\xfe broken</html>"

        def close(self):
            pass

    def fake_get(url, stream, timeout, allow_redirects):
        return FinalResponse()

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    result = http_get_text("https://start.example/badbytes", fake_get, fake_resolver)
    assert "<html>" in result
    assert "broken</html>" in result
