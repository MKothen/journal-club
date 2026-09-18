"""Render the static site from the pages the sync assembled.

The rules the templates rely on come from the spec (3.3, 5.1 and 6.6):

- A plain page must look finished. A section is rendered only when it has
  content, and nothing marks what a page lacks: no placeholders, no
  completeness meters, no badges. A page without an explainer never mentions
  one.
- An explainer is submitted HTML that runs scripts. It is copied into the
  site only while its contribution is approved and the stored file was
  fetched from that contribution's link, always as explainer.txt, and a
  session page runs it only by fetching that text into an iframe sandboxed
  with allow-scripts and without allow-same-origin. The one HTML file with
  scripts published as it is, /guide/explainer-template.html, is the
  presenter guide's starter file: this repository's code, not a submission.
- Anything a visitor typed is escaped, and a submitted link becomes a link
  only when it is http or https. Every Pages site under one account shares
  an origin, so a javascript: link would run with all of them.
- Links inside the site are relative, because it is served from a subpath,
  <account>.github.io/<repository>/.
"""

import html
import re
import shutil
import statistics
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import quote, urlparse

import segno
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup, escape

from sync.archive import read_json
from sync.assemble import Built
from sync.config import ACTION_LABELS, FORMAT_LABELS, Settings
from sync.model import Contribution, Page, Session, WishlistEntry
from sync.papers import normalise_doi
from sync.sheet import SheetData

TEMPLATES = Path(__file__).resolve().parent / "templates"
STATIC = Path(__file__).resolve().parent / "static"
# The presenter guide's starter file, published beside the guide. It is this
# repository's own code, not submitted content, so it is served as it is.
EXPLAINER_TEMPLATE = Path(__file__).resolve().parent / "explainer-template.html"
GALLERY_SIZE = 6

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# What each format asks of a presenter. Listed in FORMAT_LABELS order, which
# puts help me read this first, as the spec requires wherever formats appear.
FORMAT_NOTES = {
    "help": "Bring a paper you are stuck on. Say what you understood and where "
            "you got stuck, and the room works through it with you.",
    "full": "The whole session on a paper you want to talk about.",
    "short": "Ten minutes on one result. Two fit in a session.",
}


# -- links -------------------------------------------------------------------------

def form_link(settings: Settings, action: str, page_id: str | None = None,
              paper: str | None = None) -> str:
    """A link that opens the form with the action, and the page and paper if
    given, already filled in. Google Forms selects a multiple-choice option
    only by its exact visible text, so the link carries the action's label,
    not its code. The paper is filled in only when the form has a paper
    question, settings.entry_paper."""
    joiner = "&" if "?" in settings.form_url else "?"
    link = (f"{settings.form_url}{joiner}usp=pp_url"
            f"&{settings.entry_action}={quote(ACTION_LABELS[action])}")
    if page_id:
        link += f"&{settings.entry_page}={quote(page_id)}"
    if paper and settings.entry_paper:
        link += f"&{settings.entry_paper}={quote(paper)}"
    return link


def safe_url(url: str | None) -> str | None:
    """A submitted link if it is an absolute http or https URL, else None."""
    if not url:
        return None
    url = url.strip()
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return None
    return url


def link_label(url: str) -> str:
    """A link's host and path, short enough to read in a line of text."""
    parsed = urlparse(url)
    label = (parsed.netloc + parsed.path).removeprefix("www.").rstrip("/")
    return label if len(label) <= 48 else label[:47] + "..."


# -- what a page shows -------------------------------------------------------------

@dataclass(frozen=True)
class Paper:
    title: str | None
    authors: str | None
    venue: str | None
    year: int | None
    doi: str | None
    url: str | None


@dataclass
class View:
    """A page as the templates see it."""
    page: Page
    kind: str                 # "slot" (claimed), "guest" (open session) or "chat"
    heading: str
    paper: Paper | None
    presenter: str | None     # the claimant, or an open session's guest
    affiliation: str | None
    explainer: bool           # an approved explainer is stored and copied

    @property
    def page_id(self) -> str:
        return self.page.page_id

    @property
    def day(self) -> date:
        return self.page.session.day

    @property
    def status(self) -> str:
        return self.page.session.status

    @property
    def fmt(self) -> str | None:
        return FORMAT_LABELS[self.page.slot.fmt] if self.page.slot else None


@dataclass
class Gathering:
    """One upcoming session and its pages: one, or two short slots."""
    session: Session
    views: list[View]
    claim: str | None         # a prefilled claim link, while the session has room
    free: bool                # unclaimed, so an open paper chat unless claimed


@dataclass
class Person:
    name: str
    presented: list[View] = field(default_factory=list)
    presenting: list[View] = field(default_factory=list)
    suggested: list["Suggestion"] = field(default_factory=list)
    added: list[View] = field(default_factory=list)


@dataclass(frozen=True)
class Suggestion:
    entry: WishlistEntry
    paper: Paper | None
    title: str
    interest: int

    @property
    def names(self) -> str | None:
        """What an "I'd come" answer records to name this paper: its DOI, or
        else its link. The sheet counts interest under the DOI a value holds,
        or else its text, and ignores interest that names neither."""
        return self.entry.doi or self.entry.paper_link


def _paper(doi: str | None, title: str | None, link: str | None, papers: dict) -> Paper | None:
    """What is known about a paper: the cached doi.org record if there is one,
    otherwise the DOI or title as given (spec 6.4, step 4)."""
    cached = papers.get(doi) if doi else None
    if cached:
        return Paper(title=_plain(cached.get("title")) or title,
                     authors=_plain(cached.get("authors")), venue=_plain(cached.get("venue")),
                     year=cached.get("year"), doi=doi,
                     url=safe_url(cached.get("url")) or f"https://doi.org/{doi}")
    url = f"https://doi.org/{doi}" if doi else safe_url(link)
    if not (title or url):
        return None
    return Paper(title=title, authors=None, venue=None, year=None, doi=doi, url=url)


def _view(page: Page, data: SheetData, papers: dict, explainer: bool) -> View:
    session = page.session
    if page.slot:
        slot = page.slot
        paper = _paper(slot.doi, slot.paper_title, slot.paper_link, papers)
        heading = (paper and paper.title) or slot.doi or f"A session with {slot.presenter}"
        return View(page, "slot", heading, paper, slot.presenter, None, explainer)
    if session.kind == "open":
        spec = data.open_sessions.get(session.day, {})
        guest = session.guest
        paper = _paper(spec.get("doi"), None, None, papers)
        heading = (session.title or (paper and paper.title)
                   or (f"Open session with {guest}" if guest else "Open session"))
        return View(page, "guest", heading, paper, guest, spec.get("affiliation"), explainer)
    heading = "Cancelled session" if session.status == "cancelled" else "Open paper chat"
    return View(page, "chat", heading, None, None, None, explainer)


def _gatherings(built: Built, views: dict[str, View], settings: Settings) -> list[Gathering]:
    by_day: dict[date, list[View]] = {}
    for view in sorted(views.values(), key=lambda v: v.page_id):
        by_day.setdefault(view.day, []).append(view)
    out = []
    for session in sorted(built.sessions, key=lambda s: s.day):
        if session.status != "scheduled":
            continue
        day_views = by_day.get(session.day, [])
        slots = [v.page.slot for v in day_views if v.page.slot]
        free = session.kind == "regular" and not slots
        second_short = (session.kind == "regular" and len(slots) == 1
                        and slots[0].fmt == "short")
        claim = None
        if free or second_short:
            claim = form_link(settings, "claim", session.day.isoformat())
        out.append(Gathering(session, day_views, claim, free))
    return out


def _contributors(page: Page) -> list[str]:
    parts: list[Contribution | None] = [
        page.synthesis, page.connections, page.slides, page.explainer,
        *page.takeaways, *page.follow_ups, *page.replies,
    ]
    return list(dict.fromkeys(part.name for part in parts if part))


def _people(views: list[View], suggestions: list[Suggestion]) -> list[Person]:
    """One entry per display name, in alphabetical order, listing what each
    person presented, suggested and added. Nothing is counted or ranked. A
    page credited as presented is not listed again under added."""
    people: dict[str, Person] = {}

    def person(name: str) -> Person:
        return people.setdefault(name, Person(name))

    for view in sorted(views, key=lambda v: (v.day, v.page_id)):
        credited = None
        if view.presenter and view.status == "held":
            person(view.presenter).presented.append(view)
            credited = view.presenter
        elif view.presenter and view.status == "scheduled" and view.kind == "slot":
            person(view.presenter).presenting.append(view)
            credited = view.presenter
        for name in _contributors(view.page):
            if name != credited:
                person(name).added.append(view)
    for suggestion in suggestions:
        person(suggestion.entry.name).suggested.append(suggestion)
    return sorted(people.values(), key=lambda p: (p.name.casefold(), p.name))


def _suggestions(data: SheetData, papers: dict) -> list[Suggestion]:
    out = []
    for entry in sorted(data.wishlist, key=lambda e: e.submitted_at, reverse=True):
        paper = _paper(entry.doi, entry.paper_title, entry.paper_link, papers)
        title = ((paper and paper.title) or entry.doi
                 or (link_label(paper.url) if paper and paper.url else "A paper"))
        # The sheet counts interest under the DOI a value holds, or else its
        # text, so a link that holds a DOI is counted under that DOI.
        keys = {key for key in (entry.doi, normalise_doi(entry.paper_link), entry.paper_link) if key}
        out.append(Suggestion(entry, paper, title, sum(data.interest.get(k, 0) for k in keys)))
    return out


def _signals(built: Built, gatherings: list[Gathering]) -> list[tuple[str, str]]:
    """The three signals of spec 7 the site can compute. They count activity,
    which is not the same as intellectual value."""
    pages = list(built.pages.values())
    held = [p for p in pages if p.session.status == "held"]
    slots = [p.slot for p in pages if p.slot]
    lead_times = [(s.day - s.claimed_at.date()).days for s in slots]
    next_free = next((g.session.day for g in gatherings if g.free), None)
    median = statistics.median(lead_times) if lead_times else None
    return [
        ("Next free session", _long_date(next_free) if next_free else "None in the schedule"),
        ("Median days from claim to session", f"{median:g}" if median is not None else "No claims"),
        ("Distinct presenters", str(len({s.presenter for s in slots}))),
        ("Held sessions", str(len(held))),
        ("Held sessions with takeaways", str(sum(1 for p in held if p.takeaways))),
        ("What happened next entries", str(sum(len(p.follow_ups) for p in pages))),
        ("Author replies", str(sum(len(p.replies) for p in pages))),
    ]


# -- text --------------------------------------------------------------------------

def _long_date(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]} {day.year}"


def _day_month(day: date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]}"


def _short_date(day: date) -> str:
    return f"{day.day} {MONTHS[day.month - 1][:3]}"


def _paragraphs(text: str | None, inner: str | None = None) -> Markup:
    """Submitted text as escaped paragraphs: a blank line starts a new one, and
    a single line break is kept. `inner` wraps each paragraph's text in that
    element, such as mark."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text or "") if b.strip()]
    wrap = Markup("<{0}>{{}}</{0}>".format(inner)) if inner else Markup("{}")
    return Markup("").join(
        Markup("<p>{}</p>").format(wrap.format(Markup("<br>\n").join(b.splitlines())))
        for b in blocks
    )


def _authors(authors: str | None) -> str:
    names = [name for name in (authors or "").split(", ") if name]
    return ", ".join(names[:3]) + " et al." if len(names) > 6 else ", ".join(names)


def _sentence(text: str) -> str:
    """Text ending in one full stop. "et al." and a title that ends in a
    question mark gain none."""
    return text if text[-1:] in (".", "?", "!") else text + "."


_TAG = re.compile(r"<[^>]*>")


def _plain(text: str | None) -> str | None:
    """Metadata as plain text. Crossref titles carry inline markup such as
    <i>In vivo</i>; the tags are dropped and entities decoded, twice so that
    an entity-encoded tag goes too. The result is never marked safe: the
    templates escape it like any other text."""
    if not text:
        return None
    for _ in range(2):
        text = html.unescape(_TAG.sub("", text))
    return " ".join(text.split()) or None


# -- the guide's Markdown ------------------------------------------------------------
# The guide is written in this repository, so a small subset is enough:
# headings, paragraphs, flat lists, block quotes, fenced code, and inline
# code, links, bold and italics. Raw HTML is shown as text. Being trusted
# text, the guide may also link a relative path, such as the starter file
# published beside it; submitted content never goes through this renderer.

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBER = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_FENCE = re.compile(r"^\s*```")
_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_STRONG = re.compile(r"\*\*(.+?)\*\*")
_EM = re.compile(r"(?<![\w*])\*(?![\s*])(.+?)(?<!\s)\*(?![\w*])|(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)")
_HOLE = re.compile("\x00(\\d+)\x00")
_RELATIVE = re.compile(r"[A-Za-z0-9._/-]+(#[A-Za-z0-9_-]+)?")


def _guide_url(url: str) -> str | None:
    """A guide link's target: an http or https URL, or a relative path that
    can name neither another host nor a scheme."""
    if _RELATIVE.fullmatch(url) and not url.startswith("//") and ":" not in url:
        return url
    return safe_url(url)


def _emphasis(text: str) -> str:
    text = _STRONG.sub(r"<strong>\1</strong>", text)
    return _EM.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", text)


def _inline(text: str) -> str:
    """Code spans and finished links are held aside while emphasis is applied,
    so an underscore or asterisk inside them is never read as markup."""
    held: list[str] = []

    def hold(markup: str) -> str:
        held.append(markup)
        return f"\x00{len(held) - 1}\x00"

    def link(match: re.Match) -> str:
        url = _guide_url(html.unescape(match.group(2)))
        label = _emphasis(match.group(1))
        return hold(f'<a href="{escape(url)}">{label}</a>') if url else label

    text = _CODE.sub(lambda m: hold(f"<code>{escape(m.group(1))}</code>"), text)
    text = _LINK.sub(link, str(escape(text)))
    return _HOLE.sub(lambda m: held[int(m.group(1))], _emphasis(text))


def _starts_block(line: str) -> bool:
    return any(p.match(line) for p in (_HEADING, _BULLET, _NUMBER, _QUOTE, _FENCE))


def markdown(text: str) -> tuple[Markup | None, Markup]:
    """Render Markdown to (title, body). A level-1 heading that opens the text
    becomes the title; any later one renders as a level-2 heading."""
    lines = text.replace("\r\n", "\n").split("\n")
    blocks: list[str] = []
    title = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif _FENCE.match(line):
            end = i + 1
            while end < len(lines) and not _FENCE.match(lines[end]):
                end += 1
            blocks.append(f"<pre><code>{escape(chr(10).join(lines[i + 1:end]))}</code></pre>")
            i = end + 1
        elif _HEADING.match(line):
            match = _HEADING.match(line)
            level, body = len(match.group(1)), _inline(match.group(2))
            if level == 1 and title is None and not blocks:
                title = Markup(body)
            else:
                blocks.append(f"<h{max(level, 2)}>{body}</h{max(level, 2)}>")
            i += 1
        elif _BULLET.match(line) or _NUMBER.match(line):
            pattern, tag = (_BULLET, "ul") if _BULLET.match(line) else (_NUMBER, "ol")
            items: list[list[str]] = []
            while i < len(lines):
                item = pattern.match(lines[i])
                if item:
                    items.append([item.group(1)])
                elif lines[i].strip() and lines[i][:1] in (" ", "\t") and items:
                    items[-1].append(lines[i].strip())
                elif not lines[i].strip() and _next_matches(lines, i, pattern):
                    pass
                else:
                    break
                i += 1
            blocks.append(f"<{tag}>" + "".join(
                f"<li>{_inline(' '.join(item))}</li>" for item in items) + f"</{tag}>")
        elif _QUOTE.match(line):
            quoted = []
            while i < len(lines) and _QUOTE.match(lines[i]):
                quoted.append(_QUOTE.match(lines[i]).group(1))
                i += 1
            inner = _paragraph_blocks(quoted)
            blocks.append(f"<blockquote>{inner}</blockquote>")
        else:
            paragraph = []
            while i < len(lines) and lines[i].strip() and not (paragraph and _starts_block(lines[i])):
                paragraph.append(lines[i].strip())
                i += 1
            blocks.append(f"<p>{_inline(' '.join(paragraph))}</p>")
    return title, Markup("\n".join(blocks))


def _next_matches(lines: list[str], i: int, pattern: re.Pattern) -> bool:
    """Whether the next non-blank line after i continues the list."""
    for line in lines[i + 1:]:
        if line.strip():
            return bool(pattern.match(line))
    return False


def _paragraph_blocks(lines: list[str]) -> str:
    text = "\n".join(lines)
    return "".join(f"<p>{_inline(' '.join(b.split()))}</p>"
                   for b in re.split(r"\n\s*\n", text) if b.strip())


# -- rendering ---------------------------------------------------------------------

def _environment(settings: Settings, has_guide: bool) -> Environment:
    # autoescape=True rather than select_autoescape(): the templates end in
    # .j2, which select_autoescape's extension check would leave unescaped.
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True,
                      trim_blocks=True, lstrip_blocks=True)
    env.filters.update(long_date=_long_date, day_month=_day_month, short_date=_short_date,
                       paragraphs=_paragraphs, safe_url=safe_url, link_label=link_label,
                       authors=_authors, sentence=_sentence)
    env.globals.update(settings=settings, form_link=form_link, has_guide=has_guide,
                       clock=f"{settings.session_hour:02d}:{settings.session_minute:02d}",
                       formats=[(FORMAT_LABELS[code], FORMAT_NOTES[code]) for code in FORMAT_LABELS])
    return env


def _write(out: Path, env: Environment, path: str, template: str, **context) -> None:
    """Render `template` to <path>index.html. `root` leads back to the site's
    top from there, since every link inside the site is relative."""
    target = out / path / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    root = "../" * path.count("/") or "./"
    text = env.get_template(template).render(root=root, path=path, **context)
    target.write_text(text, encoding="utf-8", newline="\n")


def _publishes_explainer(page: Page, stored: Path, fetched: dict) -> bool:
    """Whether the stored explainer is the one currently approved for this
    page. page.explainer is set only from an approved contribution, and
    data/explainers.json records the link the stored file was fetched from.
    The two must match: after a withdrawal or a failed refetch the file on
    disk can be an older or withdrawn version, and an approved row with no
    link names no file at all. With no record, nothing is published."""
    link = page.explainer.link if page.explainer else None
    return bool(link) and fetched.get(page.page_id) == link and stored.exists()


def render(root: Path, built: Built, data: SheetData) -> None:
    """Write the whole site to root/_site, replacing what was there."""
    out = root / "_site"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copytree(STATIC, out / "static")

    settings = data.settings
    papers = read_json(root / "data" / "papers" / "cache.json", {})
    fetched = read_json(root / "data" / "explainers.json", {})
    guide_file = root / "content" / "guide.md"
    guide = guide_file.read_text(encoding="utf-8") if guide_file.exists() else None
    env = _environment(settings, has_guide=guide is not None)

    stored = {page_id: root / "explainers" / page_id / "explainer.txt" for page_id in built.pages}
    views = {
        page_id: _view(page, data, papers,
                       explainer=_publishes_explainer(page, stored[page_id], fetched))
        for page_id, page in built.pages.items()
    }
    gatherings = _gatherings(built, views, settings)
    # Newest session first, and a session's short slots in order, a before b.
    held = sorted(sorted((v for v in views.values() if v.status == "held"),
                         key=lambda v: v.page_id), key=lambda v: v.day, reverse=True)
    library: dict[int, list[View]] = {}
    for view in held:
        library.setdefault(view.day.year, []).append(view)
    suggestions = _suggestions(data, papers)

    _write(out, env, "", "index.html.j2", up_next=gatherings[0] if gatherings else None,
           upcoming=gatherings[1:], gallery=held[:GALLERY_SIZE], more=len(held) > GALLERY_SIZE)
    _write(out, env, "library/", "library.html.j2", nav="library", library=library)
    _write(out, env, "wishlist/", "wishlist.html.j2", nav="wishlist", suggestions=suggestions)
    _write(out, env, "people/", "people.html.j2", nav="people",
           people=_people(list(views.values()), suggestions))
    if guide is not None:
        title, body = markdown(guide)
        _write(out, env, "guide/", "guide.html.j2", nav="guide", title=title, body=body)
        shutil.copyfile(EXPLAINER_TEMPLATE, out / "guide" / "explainer-template.html")
    _write(out, env, "signals/", "signals.html.j2", signals=_signals(built, gatherings))

    for page_id, view in views.items():
        path = f"sessions/{page_id}/"
        siblings = [v for v in views.values() if v.day == view.day and v.page_id != page_id]
        _write(out, env, path, "session.html.j2", view=view,
               siblings=sorted(siblings, key=lambda v: v.page_id))
        folder = out / path
        segno.make_qr(form_link(settings, "takeaway", page_id)).save(
            folder / "takeaway-qr.svg", scale=4, dark="#000", light="#fff")
        if view.explainer:
            shutil.copyfile(stored[page_id], folder / "explainer.txt")
