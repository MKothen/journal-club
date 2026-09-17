"""DOI handling. doi.org content negotiation covers Crossref and DataCite,
so arXiv preprints resolve too."""

import re

import requests

DOI_RE = re.compile(r"(10\.\d{4,9}/\S+)", re.IGNORECASE)
CSL_HEADERS = {"Accept": "application/vnd.citationstyles.csl+json"}


def normalise_doi(raw: str | None) -> str | None:
    if not raw:
        return None
    match = DOI_RE.search(raw.strip())
    if not match:
        return None
    return match.group(1).rstrip(".,);").lower()


def http_fetch(url: str, headers: dict) -> dict:
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def paper_metadata(doi: str, cache: dict, fetch=http_fetch) -> dict:
    if doi in cache:
        return cache[doi]
    csl = fetch(f"https://doi.org/{doi}", CSL_HEADERS)
    record = {
        "doi": doi,
        "title": _first(csl.get("title")),
        "authors": _authors(csl.get("author", [])),
        "year": _year(csl),
        "venue": _first(csl.get("container-title")),
        "url": f"https://doi.org/{doi}",
    }
    cache[doi] = record
    return record


def _first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _authors(authors: list[dict]) -> str:
    names = []
    for author in authors:
        given = author.get("given", "")
        family = author.get("family", "")
        initial = (given[:1] + ".") if given else ""
        names.append(" ".join(part for part in (initial, family) if part))
    return ", ".join(names)


def _year(csl: dict) -> int | None:
    parts = csl.get("issued", {}).get("date-parts", [[None]])
    return parts[0][0] if parts and parts[0] else None
