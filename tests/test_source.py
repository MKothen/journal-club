from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SOURCES = sorted(p for folder in ("sync", "web", "tests") for p in (ROOT / folder).glob("*.py"))


@pytest.mark.parametrize("path", SOURCES, ids=[p.relative_to(ROOT).as_posix() for p in SOURCES])
def test_python_source_is_ascii_only(path):
    # A non-ASCII byte in source crashes tooling that reads it as cp1252 on
    # Windows. Write such a character with chr() or an escape instead.
    lines = [n for n, line in enumerate(path.read_bytes().split(b"\n"), 1)
             if any(byte > 127 for byte in line)]
    assert lines == [], f"non-ASCII bytes on lines {lines}"
