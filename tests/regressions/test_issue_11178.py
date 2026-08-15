"""Regression: escape auto-diagnose loses the real regression-pin evidence path (#11178).

Escape ledger row ``regression-pin:7fb2ed07e756b8c1aaca8a11585d2deb387509fc``
aged past the encoding threshold unresolved. Root cause: when the detecting
commit adds its OWN ``tests/regressions/`` pin — the common zero-needle case
(no issue ref, no originating sha, so ``regression_hits``'s git-grep has
nothing to search for) — ``EscapeAutoDiagnoser._gather`` recorded a literal
``"<detecting-commit-regression-pin>"`` placeholder instead of the real pin
path. The resolution is written once via the append-only ``resolve_escape``
service, so a placeholder recorded before the fix stays a placeholder
forever; only NEW rows benefit.

This pins the fix end to end: ``escape.attribution.regression_pins_added``
returns the actual added paths, ``EscapeAutoDiagnoser`` records them as the
resolution evidence, and the aging close comment names them.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from escape import attribution
from escape.auto_diagnose import EscapeAutoDiagnoser, EscapeDiagnosis
from escape.ledger import EscapeLedger
from escape.models import EscapeRecord
from escape.surfaces import SurfacedIssueLedger
from escape_ledger_loop import EscapeLedgerLoop
from mockworld.fakes.fake_github import FakeGitHub
from tests.helpers import make_bg_loop_deps

_PLACEHOLDER = "<detecting-commit-regression-pin>"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _head(repo: Path) -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@e.dev")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "-q", "-m", "init", "--allow-empty")
    return repo


def _commit_self_pin(repo: Path, filename: str) -> str:
    """A commit that adds its own regression pin and names no issue/PR — the
    zero-needle case ``regression_hits`` cannot resolve via grep."""
    reg = repo / "tests" / "regressions"
    reg.mkdir(parents=True, exist_ok=True)
    (reg / filename).write_text("def test_bug(): pass\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "test: pin regression for a live failure")
    return _head(repo)


def _pin_row(detection_ref: str, *, detected_at: str) -> EscapeRecord:
    return EscapeRecord(
        id=f"regression-pin:{detection_ref}",
        detected_at=detected_at,
        detection_source="regression-pin",
        detection_ref=detection_ref,
        originating_pr=None,
        originating_merge_sha="",
        merged_at="",
        time_to_detection_hours=None,
        attribution_method="regression-pin",
        attribution_confidence="medium",
        encoded_as="none-yet",
        notes="Adds a tests/regressions/ pin for a post-merge failure.",
    )


class TestRegressionPinEvidenceIsNotDiscarded:
    async def test_self_pin_resolution_names_the_real_path(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        sha = _commit_self_pin(repo, "test_issue_11178_live.py")

        prs = AsyncMock()
        prs.get_issue_labels = AsyncMock(return_value=[])
        diagnoser = EscapeAutoDiagnoser(
            repo_root=repo,
            prs=prs,
            ledger_path=tmp_path / "escape_ledger.jsonl",
            diagnoses_path=tmp_path / "escape_diagnoses.jsonl",
        )
        record = _pin_row(sha, detected_at="2026-01-01T00:00:00+00:00")
        EscapeLedger(diagnoser._ledger_path).append(record)

        verdict = await diagnoser.diagnose(record)

        assert verdict is EscapeDiagnosis.RESOLVED_ENCODED
        resolved = EscapeLedger(diagnoser._ledger_path).read_latest()[0]
        assert "tests/regressions/test_issue_11178_live.py" in resolved.notes
        assert _PLACEHOLDER not in resolved.notes

    def test_attribution_returns_the_real_paths_not_a_bare_bool(self) -> None:
        pins = attribution.regression_pins_added(
            ("tests/regressions/test_issue_11178_live.py", "src/mod.py")
        )
        assert pins == ("tests/regressions/test_issue_11178_live.py",)

    async def test_aging_close_comment_names_the_recorded_evidence(
        self, tmp_path: Path
    ) -> None:
        # Full loop lifecycle: an OPEN HITL link (filed before auto-diagnose
        # ran, as happened in production) is answered on a later tick — the
        # close comment must name the real evidence, not just the encoding.
        repo = _init_repo(tmp_path)
        sha = _commit_self_pin(repo, "test_issue_11178_live.py")

        github: Any = FakeGitHub()
        bg = make_bg_loop_deps(tmp_path)
        object.__setattr__(bg.config, "repo_root", repo)
        object.__setattr__(bg.config, "data_root", tmp_path / "data")
        object.__setattr__(bg.config, "escape_ledger_loop_enabled", True)
        object.__setattr__(bg.config, "escape_ledger_auto_diagnose_enabled", False)
        from unittest.mock import MagicMock

        state = MagicMock()
        state.get_escape_ledger_last_processed_sha.return_value = sha
        dedup_store: set[str] = set()
        dedup = MagicMock()
        dedup.get.side_effect = lambda: set(dedup_store)
        dedup.set_all.side_effect = lambda values: (
            dedup_store.clear() or dedup_store.update(values)
        )
        loop = EscapeLedgerLoop(
            config=bg.config,
            pr_manager=github,
            state=state,
            dedup=dedup,
            deps=bg.loop_deps,
        )
        old = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        EscapeLedger(loop._ledger_path).append(_pin_row(sha, detected_at=old))

        filed, _capped = await loop._surface_findings()
        assert filed == 1
        (link,) = SurfacedIssueLedger(loop._surfaces_path).open_links()

        object.__setattr__(bg.config, "escape_ledger_auto_diagnose_enabled", True)
        closed = await loop._reconcile_surfaced_issues()

        assert closed == 1
        assert github._issues[link.issue_number].state == "closed"
        close_comment = str(github._issues[link.issue_number].comments[-1])
        assert "tests/regressions/test_issue_11178_live.py" in close_comment
        assert _PLACEHOLDER not in close_comment
