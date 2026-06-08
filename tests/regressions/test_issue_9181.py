"""Regression for issue #9181 — FakeGit adapter-surface cassette gap.

The ``FakeCoverageAuditorLoop`` (spec §4.7) considers a fake's
adapter-surface method *covered* iff a cassette under
``tests/trust/contracts/cassettes/<adapter>/`` has an ``input.command``
naming that method. Issue #9181 reports that ``FakeGit`` exposes two
public adapter-surface methods — ``status`` and ``worktree_remove`` —
with no matching cassette under ``tests/trust/contracts/cassettes/git/``.

This test reuses the auditor's *own* catalog functions so it fails for
exactly the reason the auditor filed the issue. It goes RED until a
``status`` and a ``worktree_remove`` cassette are recorded. Do not fix
the gap here — this only reproduces it.
"""

from __future__ import annotations

from pathlib import Path

from fake_coverage_auditor_loop import (
    _FAKE_TO_CASSETTE_DIR,
    catalog_cassette_methods,
    catalog_fake_methods,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FAKE_DIR = _REPO_ROOT / "src" / "mockworld" / "fakes"
_CASSETTE_ROOT = _REPO_ROOT / "tests" / "trust" / "contracts" / "cassettes"


def test_fake_git_adapter_surface_fully_cassetted() -> None:
    catalog = catalog_fake_methods(_FAKE_DIR)
    assert "FakeGit" in catalog, "FakeGit not found in fakes catalog"

    surface = catalog["FakeGit"]["adapter-surface"]
    cassette_dir = _CASSETTE_ROOT / _FAKE_TO_CASSETTE_DIR["FakeGit"]
    cassetted = catalog_cassette_methods(cassette_dir)

    uncovered = sorted(m for m in surface if m not in cassetted)

    assert uncovered == [], (
        "FakeGit adapter-surface methods missing a cassette under "
        f"{cassette_dir.relative_to(_REPO_ROOT)}/: {uncovered}"
    )
