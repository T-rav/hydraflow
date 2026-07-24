"""Regression test for the ADR-0049/ADR-0004 dead source-file citations.

Closes #10440. ``_SOURCE_FILE_CITATION_RE`` (``src/adr_index.py``) matches
`` `src/foo.py:Symbol` `` — a single, optional ``:Symbol`` tail. Two live
citations used a doubled colon instead:

  * ADR-0049 line 74: `` `src/base_background_loop.py::LoopDeps` ``
  * ADR-0049 line 75: `` `src/bg_worker_manager.py::BGWorkerManager.is_enabled` ``

and one used a trailing ``()``:

  * ADR-0004 line 34: `` `src/agent_cli.py:build_agent_command()` ``

A `::` or trailing `()` doesn't just drop the *symbol* — the whole citation
fails to match, so the cited path never enters ``ADR.source_files`` at all
(the same #9514 failure mode ``test_adr_source_citations_exist.py`` was built
to catch, but that test only iterates already-parsed paths, so an
unparseable token was invisible to it). For ADR-0049 this meant
``base_background_loop.py`` and ``bg_worker_manager.py`` had zero drift
coverage — the P2 gate (``adr_drift.compute_drift``) could never fire for
either file, no matter what changed in them.

ADR-0004's fix has no effect on ``source_files``: a second, already-correct
`` `src/agent_cli.py:build_agent_command` `` citation exists at line 75, so
the file was already covered — the dead line-34 token was a harmless-looking
duplicate that the new token-parity ratchet
(``tests/architecture/test_adr_source_citations_exist.py``) would otherwise
have caught anyway. It's still fixed here to remove the dead token from the
source text.
"""

from __future__ import annotations

from pathlib import Path

from adr_drift import compute_drift
from adr_index import ADR, ADRIndex, parse_adr_file

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ADR_DIR = _REPO_ROOT / "docs" / "adr"
_ADR_0049_PATH = _ADR_DIR / "0049-trust-loop-kill-switch-convention.md"
_ADR_0004_PATH = _ADR_DIR / "0004-agent-cli-as-runtime.md"


def _single_adr_index(number: int) -> tuple[ADRIndex, ADR]:
    index = ADRIndex(_ADR_DIR)
    adr = next(a for a in index.adrs() if a.number == number)
    return index, adr


def test_adr_0049_cites_base_background_loop_with_loopdeps_symbol() -> None:
    adr = parse_adr_file(_ADR_0049_PATH)
    assert "src/base_background_loop.py" in adr.source_files
    assert "LoopDeps" in adr.source_symbols["src/base_background_loop.py"]


def test_adr_0049_cites_bg_worker_manager_with_is_enabled_symbol() -> None:
    adr = parse_adr_file(_ADR_0049_PATH)
    assert "src/bg_worker_manager.py" in adr.source_files
    assert "BGWorkerManager.is_enabled" in adr.source_symbols["src/bg_worker_manager.py"]


def test_adr_0049_raw_text_has_no_double_colon_citation() -> None:
    text = _ADR_0049_PATH.read_text()
    assert "base_background_loop.py::" not in text
    assert "bg_worker_manager.py::" not in text


def test_adr_0049_drift_gate_fires_on_loopdeps_symbol_change() -> None:
    """Previously impossible: the path wasn't in source_files under any input."""
    index, _ = _single_adr_index(49)
    findings = compute_drift(
        index, pr_number=10440, changed_files=["src/base_background_loop.py:LoopDeps"]
    )
    assert any(f.adr.number == 49 for f in findings)


def test_adr_0049_drift_gate_fires_on_bg_worker_manager_symbol_change() -> None:
    index, _ = _single_adr_index(49)
    findings = compute_drift(
        index,
        pr_number=10440,
        changed_files=["src/bg_worker_manager.py:BGWorkerManager.is_enabled"],
    )
    assert any(f.adr.number == 49 for f in findings)


def test_adr_0004_line_34_citation_no_longer_has_dead_paren_tail() -> None:
    text = _ADR_0004_PATH.read_text()
    assert "build_agent_command()" not in text
    # The already-correct sibling citation (line 75) still covers the file.
    adr = parse_adr_file(_ADR_0004_PATH)
    assert "build_agent_command" in adr.source_symbols["src/agent_cli.py"]
