import re
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

import pytest

from sync.assemble import build_pages
from sync.config import AMSTERDAM
from sync.model import Contribution, WishlistEntry
from tests.test_sheet import data
from web.build import form_link, render

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=AMSTERDAM)
PAGE = "2026-10-14"      # Ann's claimed session, held through Bo's takeaway (R1)
UNRECORDED = "2026-09-30"
GUEST = "2026-10-28"     # the fixture's open session, which cannot be claimed
CANCELLED = "2026-11-11"
FREE = "2026-11-25"      # the first unclaimed regular session
EXPLAINER = "<!doctype html><html><body><script>document.body.append('hi')</script></body></html>"


def rendered(tmp_path, parsed=None) -> Path:
    parsed = parsed if parsed is not None else data()
    render(tmp_path, build_pages(parsed, {}, NOW), parsed)
    return tmp_path / "_site"


def read(site: Path, *parts: str) -> str:
    return site.joinpath(*parts, "index.html").read_text(encoding="utf-8")


def all_pages(site: Path) -> dict[str, str]:
    return {str(p.relative_to(site)): p.read_text(encoding="utf-8") for p in site.rglob("*.html")}


def contribution(part, name="Ann", text="", link=None, approved=True, page_id=PAGE,
                 when=datetime(2026, 10, 16, 9, 0, tzinfo=AMSTERDAM)):
    return Contribution(page_id=page_id, part=part, name=name, text=text, link=link,
                        submitted_at=when, approved=approved, checked_by=None)


def with_explainer(tmp_path, approved=True, stored=True):
    parsed = data()
    parsed.contributions.append(
        contribution("explainer", link="https://example.org/explainer.html", approved=approved))
    if stored:
        folder = tmp_path / "explainers" / PAGE
        folder.mkdir(parents=True)
        (folder / "explainer.txt").write_text(EXPLAINER, encoding="utf-8")
    return parsed


# -- form links (R2) ----------------------------------------------------------------

def test_a_prefilled_form_link_carries_the_action_label_and_the_page():
    link = form_link(data().settings, "takeaway", PAGE)
    assert "entry.1=" + quote("Add a takeaway") in link
    assert "entry.2=2026-10-14" in link


def test_a_form_link_without_a_page_carries_only_the_action():
    link = form_link(data().settings, "interest")
    assert link.endswith("entry.1=" + quote("I'd come to this"))
    assert "entry.2" not in link


# -- explainers (R3, R5) -------------------------------------------------------------

def test_the_session_page_runs_an_explainer_only_in_a_sandboxed_frame(tmp_path):
    site = rendered(tmp_path, with_explainer(tmp_path))
    html = read(site, "sessions", PAGE)
    assert 'sandbox="allow-scripts"' in html
    assert "allow-same-origin" not in html
    assert 'fetch("explainer.txt")' in html and ".srcdoc" in html
    assert (site / "sessions" / PAGE / "explainer.txt").read_text(encoding="utf-8") == EXPLAINER


def test_an_explainer_is_never_linked_or_served_as_html(tmp_path):
    site = rendered(tmp_path, with_explainer(tmp_path))
    html = read(site, "sessions", PAGE)
    assert not re.search(r'href="[^"]*explainer', html)
    assert [p.name for p in (site / "sessions" / PAGE).iterdir()
            if "explainer" in p.name] == ["explainer.txt"]


@pytest.mark.parametrize("approved", [None, False], ids=["no contribution", "unapproved"])
def test_a_stored_explainer_is_published_only_while_approved(tmp_path, approved):
    parsed = data() if approved is None else with_explainer(tmp_path, approved=False, stored=False)
    folder = tmp_path / "explainers" / PAGE
    folder.mkdir(parents=True)
    (folder / "explainer.txt").write_text(EXPLAINER, encoding="utf-8")
    site = rendered(tmp_path, parsed)
    assert not (site / "sessions" / PAGE / "explainer.txt").exists()
    assert "<iframe" not in read(site, "sessions", PAGE)


def test_an_approved_explainer_whose_file_was_never_stored_shows_no_frame(tmp_path):
    site = rendered(tmp_path, with_explainer(tmp_path, stored=False))
    html = read(site, "sessions", PAGE)
    assert "<iframe" not in html and "<script" not in html


# -- a plain page looks finished (R5) -------------------------------------------------

def test_a_plain_page_shows_no_missing_explainer_placeholder(tmp_path):
    html = read(rendered(tmp_path), "sessions", PAGE)
    assert "missing" not in html.lower()
    assert "not yet" not in html.lower()
    assert "explainer" not in html.lower()
    assert "<script" not in html


def test_no_page_anywhere_carries_a_placeholder(tmp_path):
    for name, html in all_pages(rendered(tmp_path)).items():
        assert "missing" not in html.lower(), name
        assert "not yet" not in html.lower(), name


def test_a_section_appears_only_when_it_has_content(tmp_path):
    html = read(rendered(tmp_path), "sessions", PAGE)
    assert "What it means for our work" not in html
    assert "What happened next" not in html
    assert "reply" not in html.lower()


# -- the synthesis is signed (R5) -----------------------------------------------------

def test_the_synthesis_is_labelled_as_one_persons_account(tmp_path):
    html = read(rendered(tmp_path), "sessions", PAGE)
    assert "Discussion synthesis, prepared by Ann" in html
    assert "We were not convinced" in html


def test_the_word_verdict_appears_on_no_rendered_page(tmp_path):
    parsed = with_explainer(tmp_path)
    parsed.contributions += [
        contribution("connections", text="Relevant to the replay model"),
        contribution("next", name="Bo", text="We tried it"),
        replace(contribution("reply", name="A. Author", text="Thanks"), checked_by="Max"),
    ]
    pages = all_pages(rendered(tmp_path, parsed))
    assert len(pages) > 10
    for name, html in pages.items():
        assert "verdict" not in html.lower(), name


# -- the library and the front page (R1, R5) ------------------------------------------

def test_the_library_lists_only_held_sessions(tmp_path):
    html = read(rendered(tmp_path), "library")
    assert "2026-10-14" in html
    assert "2026-09-30" not in html


def test_the_library_lists_a_sessions_short_slots_in_order(tmp_path):
    parsed = data()
    for name, taken in (("Cy", "2026-09-21 09:00:00"), ("Dee", "2026-09-22 09:00:00")):
        parsed.claims.append({
            "name": name, "day": date(2026, 9, 30), "fmt": "short", "doi": None,
            "paper_title": f"{name}'s figure", "paper_link": None, "hidden": False,
            "submitted_at": datetime.fromisoformat(taken).replace(tzinfo=AMSTERDAM)})
    parsed.contributions += [contribution("takeaway", name="Bo", text="Yes", page_id=page)
                             for page in ("2026-09-30-a", "2026-09-30-b")]
    html = read(rendered(tmp_path, parsed), "library")
    assert html.index("2026-10-14") < html.index("2026-09-30-a") < html.index("2026-09-30-b")


def test_the_front_page_shows_open_sessions_with_a_claim_link(tmp_path):
    html = read(rendered(tmp_path))
    assert "Claim this" in html
    assert "entry.1=" + quote("Claim a session") in html
    assert f"entry.2={FREE}" in html


def test_a_guest_session_and_a_cancelled_one_offer_no_claim(tmp_path):
    html = read(rendered(tmp_path))
    assert f"entry.2={GUEST}" not in html
    assert f"entry.2={CANCELLED}" not in html


def test_the_front_page_lists_its_sections_in_the_specified_order(tmp_path):
    html = read(rendered(tmp_path))
    marks = ["Bring a paper you want help with, or one you want to talk about",
             'id="up-next"', 'id="upcoming"', 'id="gallery"']
    positions = [html.index(mark) for mark in marks]
    assert positions == sorted(positions)


def test_formats_are_listed_with_help_me_read_this_first(tmp_path):
    html = read(rendered(tmp_path))
    positions = [html.index(label) for label in
                 ("Help me read this", "Full presentation", "Short slot on one figure")]
    assert positions == sorted(positions)


def test_the_front_page_gallery_shows_held_pages_only(tmp_path):
    gallery = read(rendered(tmp_path)).split('id="gallery"')[1]
    assert f"sessions/{PAGE}/" in gallery
    assert UNRECORDED not in gallery


def test_the_gallery_does_not_mark_which_pages_have_an_explainer(tmp_path):
    site = rendered(tmp_path, with_explainer(tmp_path))
    assert (site / "sessions" / PAGE / "explainer.txt").exists()
    for html in (read(site), read(site, "library")):
        assert "explainer" not in html.lower()


def test_no_session_page_carries_a_start_here_block(tmp_path):
    for name, html in all_pages(rendered(tmp_path)).items():
        if name.startswith("sessions"):
            assert "start here" not in html.lower() and "start-here" not in html.lower(), name


def test_every_page_gets_a_takeaway_qr_code(tmp_path):
    site = rendered(tmp_path)
    assert (site / "sessions" / PAGE / "takeaway-qr.svg").exists()
    assert (site / "sessions" / FREE / "takeaway-qr.svg").exists()


def test_a_cancelled_session_page_offers_no_takeaway(tmp_path):
    html = read(rendered(tmp_path), "sessions", CANCELLED)
    assert "cancelled" in html.lower()
    assert "Add a takeaway" not in html


# -- names (R4) -----------------------------------------------------------------------

def test_the_people_page_lists_each_person_once_in_alphabetical_order(tmp_path):
    parsed = data()
    parsed.contributions.append(
        contribution("takeaway", name="Ann", text="Also mine", page_id=UNRECORDED))
    parsed.wishlist.append(WishlistEntry(
        doi=None, paper_title="A paper Ann wants", paper_link=None, name="Ann", why="",
        submitted_at=datetime(2026, 10, 1, 9, 0, tzinfo=AMSTERDAM)))
    html = read(rendered(tmp_path, parsed), "people")
    assert html.count(">Ann</h2>") == 1
    assert html.count(">Bo de Vries</h2>") == 1
    assert html.index(">Ann</h2>") < html.index(">Bo de Vries</h2>")
    assert "A paper Ann wants" in html


# -- what visitors submit never runs on the site's origin --------------------------------

def test_a_link_that_is_not_http_is_never_rendered(tmp_path):
    parsed = data()
    parsed.claims[0]["paper_link"] = "javascript:alert(1)"
    parsed.contributions.append(
        contribution("next", name="Bo", text="Look", link="javascript:alert(2)"))
    parsed.wishlist.append(WishlistEntry(
        doi=None, paper_title="Bad", paper_link="javascript:alert(3)", name="Cy", why="",
        submitted_at=datetime(2026, 10, 1, 9, 0, tzinfo=AMSTERDAM)))
    for name, html in all_pages(rendered(tmp_path, parsed)).items():
        assert "javascript:" not in html, name


def test_submitted_text_and_names_are_escaped(tmp_path):
    parsed = data()
    parsed.contributions.append(
        contribution("takeaway", name="<i>Mallory</i>", text="<script>alert(1)</script>"))
    site = rendered(tmp_path, parsed)
    for html in (read(site, "sessions", PAGE), read(site, "people")):
        assert "<i>Mallory" not in html and "&lt;i&gt;Mallory" in html
    html = read(site, "sessions", PAGE)
    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;alert(1)" in html


def test_the_site_loads_nothing_from_elsewhere(tmp_path):
    site = rendered(tmp_path, with_explainer(tmp_path))
    for name, html in all_pages(site).items():
        for url in re.findall(r'<(?:script|link|img|iframe)\b[^>]*\b(?:src|href)="([^"]*)"', html):
            assert not re.match(r"^(https?:)?//", url), (name, url)
        assert "<script src" not in html, name
        scripts = re.findall(r"<script\b.*?</script>", html, re.S)
        assert all('fetch("explainer.txt")' in script for script in scripts), name
    css = (site / "static" / "style.css").read_text(encoding="utf-8")
    assert "@import" not in css and "url(" not in css


# -- the guide and the signals page ---------------------------------------------------

def test_the_guide_renders_its_markdown(tmp_path):
    guide = tmp_path / "content" / "guide.md"
    guide.parent.mkdir()
    guide.write_text(
        "# Presenter guide\n\n## Help me read this\n\nBring a paper you are **stuck** on.\n\n"
        "- one\n- two, see [the form](https://example.org/form)\n\n"
        "Keep `my_file_name` and [the _draft_](https://example.org/_draft_) intact.\n\n"
        "<script>alert(1)</script> and [bad](javascript:alert(1))\n",
        encoding="utf-8")
    html = read(rendered(tmp_path), "guide")
    assert "<h1>Presenter guide</h1>" in html
    assert "<h2>Help me read this</h2>" in html
    assert "<strong>stuck</strong>" in html
    assert "<li>two, see <a href=\"https://example.org/form\">the form</a></li>" in html
    assert "<code>my_file_name</code>" in html
    assert '<a href="https://example.org/_draft_">the <em>draft</em></a>' in html
    assert "<script>alert" not in html and "javascript:" not in html


def test_without_a_guide_there_is_no_guide_page_and_no_link_to_one(tmp_path):
    site = rendered(tmp_path)
    assert not (site / "guide").exists()
    assert "guide/" not in read(site)


def test_the_signals_page_exists_but_is_not_in_the_navigation(tmp_path):
    site = rendered(tmp_path)
    assert "Distinct presenters" in read(site, "signals")
    for name, html in all_pages(site).items():
        if not name.startswith("signals"):
            assert "signals/" not in html, name
