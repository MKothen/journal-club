import pytest
from sync.explainers import (
    ExplainerError,
    check_host,
    download_url,
    fetch_explainer,
    store_explainer,
)


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


def test_stored_file_byte_length_matches_input(tmp_path):
    body = "<html>\nLine 2\nLine 3</html>"
    path = store_explainer(tmp_path, "2026-10-07", body)
    file_bytes = path.read_bytes()
    expected_bytes = body.encode("utf-8")
    assert len(file_bytes) == len(expected_bytes)
    assert file_bytes == expected_bytes


def test_http_get_text_sets_utf8_when_no_charset_in_header():
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html"}
        encoding = None

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield "<html>Test</html>".encode("utf-8")

    def fake_get(url, stream, timeout, allow_redirects):
        return FakeResponse()

    from sync.explainers import http_get_text
    result = http_get_text("https://example.com/test", fake_get)
    assert "<html>Test</html>" in result


def test_streaming_stops_when_size_exceeded():
    chunks = ["<html>", "x" * 65536, "x" * 65536, "x" * 65536, "x" * 10_000_001]
    chunk_iter = iter(chunks)

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        encoding = "utf-8"

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            for chunk in chunk_iter:
                yield chunk.encode("utf-8") if isinstance(chunk, str) else chunk

    def fake_get(url, stream, timeout, allow_redirects):
        return FakeResponse()

    from sync.explainers import http_get_text
    with pytest.raises(ExplainerError, match="large"):
        http_get_text("https://example.com/test", fake_get)


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


def test_google_signin_page_is_rejected():
    def fake_fetch(url):
        return """<html>
        <title>Sign in - Google Accounts</title>
        <body>Please sign in</body>
        </html>"""

    def fake_resolver(host, port):
        if host == "accounts.google.com":
            return [(2, 1, 6, "", ("142.251.32.14", 0))]
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with pytest.raises(ExplainerError, match="sign-in"):
        fetch_explainer("https://accounts.google.com/test", fake_fetch, fake_resolver)


def test_google_virus_scan_warning_is_rejected():
    def fake_fetch(url):
        return "<html><body>Virus scan warning</body></html>"

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with pytest.raises(ExplainerError, match="sign-in"):
        fetch_explainer("https://drive.google.com/test", fake_fetch, fake_resolver)


def test_google_accounts_signin_text_is_rejected():
    def fake_fetch(url):
        return "<html><body>Sign in - Google Accounts page</body></html>"

    def fake_resolver(host, port):
        return [(2, 1, 6, "", ("8.8.8.8", 0))]

    with pytest.raises(ExplainerError, match="sign-in"):
        fetch_explainer("https://drive.google.com/test", fake_fetch, fake_resolver)
