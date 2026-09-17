import pytest
from sync.explainers import ExplainerError, download_url, fetch_explainer, store_explainer


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
