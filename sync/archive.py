"""Write the data files that the site builds from, and that outlive the sheet.

Two promises rest on this module:

- The claim-id map in data/slots.json is written whole, never pruned to the
  live claims. claims.resolve_claims retires every id that has ever appeared
  in it, so dropping a hidden claim's entry would let its id be reissued and
  move that page's takeaways onto someone else's page.
- The git archive, data/submissions.json, holds only publishable
  contributions. The repository is public and its history cannot be
  withdrawn, so an unapproved author reply must never reach it, even though
  the site already refuses to show one.
"""

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path

from sync.contributions import archivable, publishable


def _plain(value):
    if is_dataclass(value):
        return {k: _plain(v) for k, v in asdict(value).items()}
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    """Sorted keys and LF line endings, so the same data gives the same bytes
    on any machine and git sees no change when nothing changed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_plain(value), indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def write_data(root: Path, built, data, now: datetime) -> None:
    write_json(root / "data" / "slots.json", built.assigned)
    write_json(root / "data" / "schedule.json", built.sessions)
    write_json(root / "data" / "submissions.json",
               archivable(publishable(data.contributions), now))
    # No last_run here: it changed on every run and so forced a commit on
    # every run, about 8 a day. keepalive_month is all the keep-alive needs
    # -- it still forces one commit on the first run of a new month, which
    # is enough to keep GitHub from disabling the schedule after 60 quiet
    # days, and a run that changes nothing else now commits nothing.
    write_json(root / "data" / "sync_state.json",
               {"keepalive_month": now.strftime("%Y-%m")})
