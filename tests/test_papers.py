import pytest
from sync.papers import normalise_doi, paper_metadata


def test_a_doi_url_is_reduced_to_the_bare_doi():
    assert normalise_doi("https://doi.org/10.1038/nn.2479") == "10.1038/nn.2479"
    assert normalise_doi(" doi:10.1038/NN.2479 ") == "10.1038/nn.2479"


def test_nonsense_is_not_a_doi():
    assert normalise_doi("see the pdf I sent") is None


def test_metadata_is_fetched_once_and_then_cached():
    calls = []

    def fetch(url, headers):
        calls.append(url)
        return {"title": ["A paper"], "author": [{"given": "A", "family": "Author"}],
                "issued": {"date-parts": [[2025]]}, "container-title": ["A Journal"]}

    cache = {}
    first = paper_metadata("10.1000/xyz", cache, fetch)
    second = paper_metadata("10.1000/xyz", cache, fetch)
    assert first["title"] == "A paper"
    assert first["authors"] == "A. Author"
    assert first["year"] == 2025
    assert second == first
    assert len(calls) == 1


def test_a_failed_lookup_is_not_cached_so_the_next_run_retries():
    def fetch(url, headers):
        raise RuntimeError("503")

    cache = {}
    with pytest.raises(RuntimeError):
        paper_metadata("10.1000/xyz", cache, fetch)
    assert cache == {}
