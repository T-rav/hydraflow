"""Regression guard for issue #9505.

Two ADR files sharing the same four-digit number (e.g. ``0064-a.md`` and
``0064-b.md``) previously caused the first file's cited modules to be silently
dropped when a downstream consumer built ``{r.adr_id: r for r in
idx.adr_to_modules}`` — the second ADRRef entry with the same adr_id overwrote
the first in the dict.  The fix merges cited_modules per adr_id (union) so
every file's references are preserved in a single row.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from arch.extractors.adr_xref import extract_adr_refs


@pytest.fixture
def adr_dir(tmp_path: Path) -> Path:
    d = tmp_path / "docs" / "adr"
    d.mkdir(parents=True)
    (d / "0064-a.md").write_text(dedent("# ADR-0064-a\n\nSee src/foo.py.\n"))
    (d / "0064-b.md").write_text(dedent("# ADR-0064-b\n\nSee src/bar.py:Bar.\n"))
    return d


def test_no_cited_module_is_dropped_on_number_collision(adr_dir: Path) -> None:
    idx = extract_adr_refs(adr_dir)
    by_id = {r.adr_id: r for r in idx.adr_to_modules}
    assert len(by_id) == 1, "colliding adr_ids must produce exactly one row"
    mods = by_id["ADR-0064"].cited_modules
    assert "src.foo" in mods, (
        "src/foo.py (from first file) must not be silently dropped"
    )
    assert "src.bar" in mods, "src/bar.py (from second file) must be present"
