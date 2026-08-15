"""Regression test for #11195 — ADR-dependent regression pins must self-retire.

``test_issue_10565.py`` pins ADR-0013 via
``next(a for a in adrs if a.number == 13)`` with no default. If ADR-0013 is
ever renumbered, removed, or its file dropped, that raises an unhandled
``StopIteration`` in CI on a completely unrelated PR — the same
non-self-retiring shape #11180/#11186/#11192 each fixed in a sibling module.
The reference shape is ``tests/regressions/test_issue_9176.py``, which uses
``next((...), None)`` and keeps holding when the ADR disappears.

Differential guard: this test executes the real ``test_issue_10565`` pin
function against a copy of ``docs/adr`` where ADR-0013 is renumbered,
removed, or left intact (see
``docs/architecture/adr-pin-self-retirement.likec4``). After the fix, the
pin must self-retire (``pytest.skip``) when ADR-0013 is absent, and must
still run its real assertion — not vacuously skip — when ADR-0013 is intact.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.regressions import test_issue_10565 as pin

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REAL_ADR_DIR = _REPO_ROOT / "docs" / "adr"


def _fake_adr_tree(tmp_path: Path) -> Path:
    fake_dir = tmp_path / "adr"
    shutil.copytree(_REAL_ADR_DIR, fake_dir)
    return fake_dir


def _adr_0013_file(fake_dir: Path) -> Path:
    (adr_path,) = list(fake_dir.glob("0013-*.md"))
    return adr_path


def _run_pin(monkeypatch: pytest.MonkeyPatch, fake_dir: Path) -> None:
    monkeypatch.setattr(pin, "_ADR_DIR", fake_dir)
    pin.test_adr_0013_superseded_is_never_nudged()


def test_renumbered_adr_0013_self_retires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_dir = _fake_adr_tree(tmp_path)
    adr_path = _adr_0013_file(fake_dir)
    adr_path.write_text(adr_path.read_text().replace("ADR-0013", "ADR-0913", 1))

    with pytest.raises(pytest.skip.Exception):
        _run_pin(monkeypatch, fake_dir)


def test_removed_adr_0013_self_retires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_dir = _fake_adr_tree(tmp_path)
    _adr_0013_file(fake_dir).unlink()

    with pytest.raises(pytest.skip.Exception):
        _run_pin(monkeypatch, fake_dir)


def test_intact_fixture_tree_is_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Counter-pin: an untouched copy must run the real assertion, not skip —
    proves the fix keys the skip on absence, not on an unconditional/always-true
    check that would leave the pin vacuous."""
    fake_dir = _fake_adr_tree(tmp_path)

    _run_pin(monkeypatch, fake_dir)
