"""Regression guard for #10440 — ADR source-file citations must not use `::`.

`docs/adr/0049-trust-loop-kill-switch-convention.md` cited
`` `src/base_background_loop.py::LoopDeps` `` with a doubled colon. The drift
regex ``_SOURCE_FILE_CITATION_RE`` in ``src/adr_index.py`` matches
``path.py:Symbol`` (a SINGLE colon), so a ``::`` tail parses to nothing — the
citation silently contributes no coverage and ``base_background_loop.py`` was
absent from ADR-0049's drift set (dead drift coverage). Fix: single colon.

Two guards:

1. No ADR uses a ``src/….py::`` double-colon citation (broad — this class of
   typo can never silently kill drift coverage again).
2. ADR-0049's ``base_background_loop.py:LoopDeps`` citation actually parses via
   the real drift regex (pins the fix direction, not just the absence of ``::``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from adr_index import _SOURCE_FILE_CITATION_RE

_ADR_DIR = Path(__file__).resolve().parents[2] / "docs" / "adr"
# A backtick-wrapped src/*.py citation immediately followed by a second colon.
_DOUBLE_COLON_PY = re.compile(r"`src/[^`\s]+\.py::")


def _adr_files() -> list[Path]:
    return sorted(_ADR_DIR.glob("[0-9]*.md"))


@pytest.mark.parametrize("adr", _adr_files(), ids=lambda p: p.name)
def test_no_double_colon_py_citation(adr: Path) -> None:
    """A `src/….py::Symbol` citation is unparseable by the drift regex (#10440)."""
    hits = _DOUBLE_COLON_PY.findall(adr.read_text(encoding="utf-8"))
    assert hits == [], (
        f"{adr.name}: double-colon `.py::` citation(s) parse to no drift "
        f"coverage — use a single colon `path.py:Symbol` (#10440): {hits}"
    )


def test_adr0049_base_background_loop_citation_parses() -> None:
    """The fixed ADR-0049 citation resolves to its file via the real drift regex."""
    text = (_ADR_DIR / "0049-trust-loop-kill-switch-convention.md").read_text(
        encoding="utf-8"
    )
    assert "`src/base_background_loop.py:LoopDeps`" in text
    m = _SOURCE_FILE_CITATION_RE.search("`src/base_background_loop.py:LoopDeps`")
    assert m is not None and m.group(1) == "src/base_background_loop.py"
