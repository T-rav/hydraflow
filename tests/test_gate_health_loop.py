"""Tests for GateHealthLoop (#9974) — the pure engine and the loop wiring."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from gate_health_loop import (
    GateHealthLoop,
    find_born_broken,
    find_missing_artifacts,
    find_uncorrelated_blame,
    finding_fingerprint,
    is_docs_only,
    tally_job_stats,
)
from tests.helpers import make_bg_loop_deps

# ---------------------------------------------------------------------------
# Pure engine
# ---------------------------------------------------------------------------


def _rec(name: str, conclusion: str, **kw) -> dict:
    return {"name": name, "conclusion": conclusion, "created_at": "2026-07-01", **kw}


class TestTallyJobStats:
    def test_counts_passes_and_failures_per_check(self) -> None:
        stats = tally_job_stats(
            [
                _rec("Tests", "success"),
                _rec("Tests", "failure"),
                _rec("Lint", "success"),
            ]
        )
        assert stats["Tests"].passes == 1
        assert stats["Tests"].failures == 1
        assert stats["Lint"].failures == 0

    def test_skipped_and_cancelled_are_not_attempts(self) -> None:
        stats = tally_job_stats(
            [_rec("Sandbox", "skipped"), _rec("Sandbox", "cancelled")]
        )
        assert "Sandbox" not in stats

    def test_docs_only_failures_tracked_with_pr(self) -> None:
        stats = tally_job_stats(
            [_rec("Tests", "failure", docs_only=True, pr_number=42)]
        )
        assert stats["Tests"].docs_only_failures == 1
        assert stats["Tests"].docs_only_prs == [42]


class TestFindBornBroken:
    def test_never_green_check_flagged_at_threshold(self) -> None:
        stats = tally_job_stats([_rec("s51 gate", "failure")] * 3)
        findings = find_born_broken(stats, min_attempts=3)
        assert [f["check"] for f in findings] == ["s51 gate"]
        assert findings[0]["failures"] == 3

    def test_single_pass_clears_the_flag(self) -> None:
        stats = tally_job_stats(
            [_rec("Gate", "failure")] * 5 + [_rec("Gate", "success")]
        )
        assert find_born_broken(stats, min_attempts=3) == []

    def test_below_threshold_not_flagged(self) -> None:
        stats = tally_job_stats([_rec("Gate", "failure")] * 2)
        assert find_born_broken(stats, min_attempts=3) == []


class TestFindUncorrelatedBlame:
    def test_code_check_failing_docs_only_prs_flagged(self) -> None:
        stats = tally_job_stats(
            [
                _rec("Tests", "failure", docs_only=True, pr_number=1),
                _rec("Tests", "failure", docs_only=True, pr_number=2),
            ]
        )
        findings = find_uncorrelated_blame(stats, min_occurrences=2)
        assert findings[0]["check"] == "Tests"
        assert findings[0]["example_prs"] == [1, 2]

    def test_non_code_check_ignored(self) -> None:
        stats = tally_job_stats(
            [_rec("Docs Build", "failure", docs_only=True, pr_number=1)] * 3
        )
        assert find_uncorrelated_blame(stats, min_occurrences=2) == []


class TestMissingArtifactsAndHelpers:
    def test_zero_artifact_failures_grouped_by_workflow(self) -> None:
        findings = find_missing_artifacts(
            [
                {"workflow": "Sandbox", "run_id": 1, "artifact_count": 0},
                {"workflow": "Sandbox", "run_id": 2, "artifact_count": 0},
                {"workflow": "Sandbox", "run_id": 3, "artifact_count": 2},
            ]
        )
        assert findings[0]["failed_runs_without_artifacts"] == 2

    def test_docs_only_classifier(self) -> None:
        assert is_docs_only(["docs/wiki/a.md", "README.md"])
        assert not is_docs_only(["docs/a.md", "src/app.py"])
        assert not is_docs_only([])

    def test_fingerprint_stable_across_growing_counts(self) -> None:
        a = finding_fingerprint({"kind": "born_broken", "check": "Gate", "failures": 3})
        b = finding_fingerprint({"kind": "born_broken", "check": "Gate", "failures": 9})
        assert a == b


# ---------------------------------------------------------------------------
# Loop wiring
# ---------------------------------------------------------------------------


def _make_loop(tmp_path: Path, **overrides):
    deps = make_bg_loop_deps(tmp_path, **overrides)
    prs = MagicMock()
    prs.list_workflow_runs = AsyncMock(return_value=[])
    prs.get_workflow_run_jobs = AsyncMock(return_value=[])
    prs.count_workflow_run_artifacts = AsyncMock(return_value=1)
    prs.get_pr_diff_names = AsyncMock(return_value=["src/app.py"])
    prs.get_issue_state = AsyncMock(return_value="OPEN")
    prs.create_issue = AsyncMock(return_value=123)
    loop = GateHealthLoop(config=deps.config, pr_manager=prs, deps=deps.loop_deps)
    return loop, prs


class TestGateHealthLoop:
    @pytest.mark.asyncio
    async def test_runtime_kill_switch(self, tmp_path: Path) -> None:
        loop, _ = _make_loop(tmp_path, enabled=False)
        assert await loop._do_work() == {"status": "disabled"}

    @pytest.mark.asyncio
    async def test_config_kill_switch(self, tmp_path: Path) -> None:
        loop, prs = _make_loop(tmp_path)
        object.__setattr__(loop._config, "gate_health_loop_enabled", False)
        assert await loop._do_work() == {"status": "config_disabled"}
        prs.list_workflow_runs.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_runs_is_clean_noop(self, tmp_path: Path) -> None:
        loop, _ = _make_loop(tmp_path)
        result = await loop._do_work()
        assert result == {"status": "no_runs", "findings": 0}

    @pytest.mark.asyncio
    async def test_listing_failure_is_fail_soft(self, tmp_path: Path) -> None:
        loop, prs = _make_loop(tmp_path)
        prs.list_workflow_runs.side_effect = RuntimeError("gh down")
        result = await loop._do_work()
        assert result == {"status": "runs_unavailable"}

    @pytest.mark.asyncio
    async def test_born_broken_finding_filed_once(self, tmp_path: Path) -> None:
        loop, prs = _make_loop(tmp_path)
        prs.list_workflow_runs.return_value = [
            {
                "id": i,
                "workflow": "CI",
                "conclusion": "failure",
                "created_at": f"2026-07-0{i}",
                "pr_number": 0,
            }
            for i in (1, 2, 3)
        ]
        prs.get_workflow_run_jobs.return_value = [
            {"name": "rc gate", "conclusion": "failure"}
        ]

        first = await loop._do_work()
        second = await loop._do_work()

        assert first["filed"] == 1
        assert second["filed"] == 0  # deduped by fingerprint
        prs.create_issue.assert_awaited_once()
        title, _body = prs.create_issue.await_args.args[0:2]
        assert "0% pass rate" in title
        assert prs.create_issue.await_args.kwargs["labels"] == ["hydraflow-find"]

    @pytest.mark.asyncio
    async def test_stale_quarantine_files_consent_package(self, tmp_path: Path) -> None:
        loop, prs = _make_loop(tmp_path)
        scen_dir = (
            Path(loop._config.repo_root) / "tests" / "sandbox_scenarios" / "scenarios"
        )
        scen_dir.mkdir(parents=True)
        (scen_dir / "s99_example.py").write_text('QUARANTINED = "#123"\n')
        prs.get_issue_state.return_value = "COMPLETED"
        prs.list_workflow_runs.return_value = [
            {
                "id": 1,
                "workflow": "CI",
                "conclusion": "success",
                "created_at": "2026-07-01",
                "pr_number": 0,
            }
        ]
        prs.get_workflow_run_jobs.return_value = [
            {"name": "Tests", "conclusion": "success"}
        ]

        result = await loop._do_work()

        assert result["filed"] == 1
        _title, body = prs.create_issue.await_args.args[0:2]
        assert "Consent package" in body
        assert "sed -i" in body  # exact command, human-gated

    @pytest.mark.asyncio
    async def test_read_only_no_finding_no_write(self, tmp_path: Path) -> None:
        loop, prs = _make_loop(tmp_path)
        prs.list_workflow_runs.return_value = [
            {
                "id": 1,
                "workflow": "CI",
                "conclusion": "success",
                "created_at": "2026-07-01",
                "pr_number": 0,
            }
        ]
        prs.get_workflow_run_jobs.return_value = [
            {"name": "Tests", "conclusion": "success"}
        ]

        result = await loop._do_work()

        assert result["findings"] == 0
        prs.create_issue.assert_not_awaited()
