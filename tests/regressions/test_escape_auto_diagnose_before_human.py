"""Regression: EscapeLedgerLoop auto-diagnoses a low-confidence escape BEFORE
routing it to a human (ADR-0115, receipts #10748 / #10749).

The recurring gap: a low-confidence escape whose bug is already regression-
encoded was filed as a ``hydraflow-find`` HITL surface for a human to confirm,
even though the confirm-or-dismiss move was mechanical. This pins the routing:

  - real + regression-encoded  → auto-resolved, NO human surface filed;
  - clear false positive        → auto-dismissed, NO human surface filed;
  - genuinely inconclusive      → the human surface IS filed (escalation kept);
  - flag OFF                     → unchanged (human surface fires).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from dedup_store import DedupStore
from escape.ledger import EscapeLedger
from escape.models import EscapeRecord
from escape_ledger_loop import EscapeLedgerLoop
from mockworld.fakes.fake_github import FakeGitHub
from tests.helpers import make_bg_loop_deps


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
    (repo / "src").mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@e.dev")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "-q", "-m", "init", "--allow-empty")
    return repo


def _commit_regression(repo: Path, issue: int) -> None:
    reg = repo / "tests" / "regressions"
    reg.mkdir(parents=True, exist_ok=True)
    (reg / f"test_bug_{issue}.py").write_text(
        f"# regression pin for #{issue}\ndef test_bug(): pass\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"test: pin regression for #{issue}")


def _commit_bug_fix(repo: Path, issue: int, *, mod: str = "crash") -> str:
    (repo / "src" / f"{mod}.py").write_text(f"def {mod}():\n    return 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"fix: resolve {mod} (fixes #{issue})")
    return _head(repo)


def _low_conf_bug_row(detection_ref: str, issue: int) -> EscapeRecord:
    return EscapeRecord(
        id=f"bug-issue:{detection_ref}",
        detected_at="2026-07-27T00:00:00+00:00",  # fresh → only the LOW surface
        detection_source="bug-issue",
        detection_ref=detection_ref,
        originating_pr=issue,
        originating_merge_sha="",
        merged_at="",
        time_to_detection_hours=None,
        attribution_method="fixes-chain",
        attribution_confidence="low",
        encoded_as="none-yet",
        notes=f"Fix commit closing #{issue}.",
    )


def _build_loop(
    tmp_path: Path, repo: Path, github: Any, *, auto_diagnose: bool
) -> EscapeLedgerLoop:
    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "repo_root", repo)
    object.__setattr__(bg.config, "data_root", tmp_path / "data")
    object.__setattr__(bg.config, "escape_ledger_loop_enabled", True)
    object.__setattr__(
        bg.config, "escape_ledger_auto_diagnose_enabled", auto_diagnose
    )
    dedup = DedupStore("escape", tmp_path / "dedup.json")
    return EscapeLedgerLoop(
        config=bg.config,
        pr_manager=github,
        state=MagicMock(),
        dedup=dedup,
        deps=bg.loop_deps,
    )


class TestEscapeAutoDiagnoseBeforeHuman:
    async def test_real_and_encoded_is_auto_resolved_no_human_surface(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        _commit_regression(repo, 123)
        fix_sha = _commit_bug_fix(repo, 123)
        github = FakeGitHub()
        loop = _build_loop(tmp_path, repo, github, auto_diagnose=True)
        EscapeLedger(loop._ledger_path).append(_low_conf_bug_row(fix_sha, 123))

        filed, capped = await loop._surface_findings()

        assert filed == 0, "machine-resolvable escape must NOT reach a human"
        assert capped is False
        resolved = EscapeLedger(loop._ledger_path).read_latest()[0]
        assert resolved.attribution_confidence == "high"
        assert resolved.encoded_as == "regression-test"

    async def test_false_positive_is_auto_dismissed_no_human_surface(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path)
        fix_sha = _commit_bug_fix(repo, 200)  # no regression test
        github = FakeGitHub()
        github.add_issue(200, "Update docs", "doc", labels=["documentation"])
        loop = _build_loop(tmp_path, repo, github, auto_diagnose=True)
        EscapeLedger(loop._ledger_path).append(_low_conf_bug_row(fix_sha, 200))

        filed, _capped = await loop._surface_findings()

        assert filed == 0, "clear false positive must NOT reach a human"

    async def test_inconclusive_still_reaches_a_human(self, tmp_path: Path) -> None:
        # No regression encoding AND the referenced issue is unknown/unlabelled
        # → the machine cannot resolve or dismiss → the human surface IS filed.
        repo = _init_repo(tmp_path)
        fix_sha = _commit_bug_fix(repo, 300)
        github = FakeGitHub()
        loop = _build_loop(tmp_path, repo, github, auto_diagnose=True)
        EscapeLedger(loop._ledger_path).append(_low_conf_bug_row(fix_sha, 300))

        filed, _capped = await loop._surface_findings()

        assert filed == 1, "a genuinely-inconclusive escape must still reach a human"

    async def test_flag_off_files_the_human_surface_unchanged(
        self, tmp_path: Path
    ) -> None:
        # Even a machine-resolvable escape files the human surface when the
        # feature is off — proving the flag gates the new routing.
        repo = _init_repo(tmp_path)
        _commit_regression(repo, 400)
        fix_sha = _commit_bug_fix(repo, 400)
        github = FakeGitHub()
        loop = _build_loop(tmp_path, repo, github, auto_diagnose=False)
        EscapeLedger(loop._ledger_path).append(_low_conf_bug_row(fix_sha, 400))

        filed, _capped = await loop._surface_findings()

        assert filed == 1
