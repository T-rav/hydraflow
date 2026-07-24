"""Regression for issue #10437 — ADR-0106 bare-cites `src/base_background_loop.py`.

`src/base_background_loop.py` is the shared per-cycle-watchdog loop base
class (#9455/#9556). ADR-0106 (Thread-level event-loop freeze detector)
bare-cites it in Context as prior art — the pre-existing asyncio watchdog
this ADR's thread-level detector fills a gap next to, not a decision ADR-0106
itself owns. Any high-churn loop-base change (PR #10414's restart-cadence
guard) therefore false-positived ADR-0106 drift.

Fix: add `src/base_background_loop.py` to `_SHARED_INFRA_MODULES`
(mirrors the pr_manager/dashboard/contract_* precedent from #9397 /
2026-06-13) so a bare, file-only citation of it no longer drifts — an ADR
that genuinely owns a `base_background_loop.py` symbol still cites it at
`:Symbol` granularity to drift.
"""

from __future__ import annotations

from pathlib import Path

from adr_drift import _SHARED_INFRA_MODULES, compute_drift
from adr_index import ADRIndex

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ADR_DIR = _REPO_ROOT / "docs" / "adr"


def _write_adr(adr_dir: Path, *, number: int, title: str, related_files: list[str]) -> None:
    related = ", ".join(f"`{f}`" for f in related_files)
    body = (
        f"# ADR-{number:04d}: {title}\n\n"
        f"- **Status:** Accepted\n"
        f"- **Date:** 2026-01-01\n"
        f"- **Related:** {related}\n\n"
        f"## Context\n\nFixture body.\n"
    )
    (adr_dir / f"{number:04d}-{title.lower()}.md").write_text(body)


def test_base_background_loop_is_shared_infra() -> None:
    assert "src/base_background_loop.py" in _SHARED_INFRA_MODULES


def test_bare_citation_of_base_background_loop_does_not_drift(tmp_path: Path) -> None:
    # A synthetic ADR that bare-cites the shared loop base class must not
    # drift on a file-only touch of it — the residual false-positive
    # source behind #10437 (PR #10414 touched the module without touching
    # any ADR that bare-cites it).
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_adr(
        adr_dir,
        number=61,
        title="depends on loop base",
        related_files=["src/base_background_loop.py"],
    )
    findings = compute_drift(
        ADRIndex(adr_dir),
        pr_number=10414,
        changed_files=["src/base_background_loop.py"],
    )
    assert findings == []


def test_symbol_citation_of_base_background_loop_still_drifts(tmp_path: Path) -> None:
    # An ADR that genuinely owns a base_background_loop.py symbol still
    # drifts when that symbol changes.
    adr_dir = tmp_path / "adr"
    adr_dir.mkdir()
    _write_adr(
        adr_dir,
        number=62,
        title="owns loop base symbol",
        related_files=["src/base_background_loop.py:BaseBackgroundLoop"],
    )
    findings = compute_drift(
        ADRIndex(adr_dir),
        pr_number=1,
        changed_files=["src/base_background_loop.py:BaseBackgroundLoop"],
    )
    assert len(findings) == 1
    assert findings[0].adr.number == 62


def test_adr_0106_does_not_drift_on_base_background_loop_file_only_touch() -> None:
    # End-to-end: the real ADR-0106 bare-cites `src/base_background_loop.py`
    # in Context. A file-only diff of just that module (production's
    # bare-path, no-symbol-evidence shape — PR #10414's actual diff) must
    # not drift ADR-0106.
    index = ADRIndex(_ADR_DIR)
    adr = next(a for a in index.adrs() if a.number == 106)
    assert "src/base_background_loop.py" in adr.source_files

    findings = compute_drift(
        index,
        pr_number=10414,
        changed_files=["src/base_background_loop.py"],
    )
    own = [f for f in findings if f.adr.number == 106]
    assert own == []
