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
    find_suspected_hangs,
    find_uncorrelated_blame,
    finding_fingerprint,
    is_docs_only,
    tally_job_stats,
)
from tests.helpers import make_bg_loop_deps


def _cancelled_job(
    *,
    name: str = "Tests",
    run_id: int = 555,
    pr_number: int = 42,
    started_at: str = "2026-07-19T00:00:00Z",
    completed_at: str = "2026-07-19T00:30:05Z",
    test_step_conclusion: str | None = None,
) -> dict:
    """A cancelled job record shaped like ``_collect``'s enriched output.

    Defaults to the #9983/#10002 signature: ~30m duration (matches the
    ``Tests`` job's real 30-minute timeout-minutes), test step never
    reaching a terminal conclusion.
    """
    return {
        "name": name,
        "conclusion": "cancelled",
        "run_id": run_id,
        "pr_number": pr_number,
        "started_at": started_at,
        "completed_at": completed_at,
        "steps": [
            {"name": "Install dependencies", "conclusion": "success"},
            {"name": "Run tests with coverage", "conclusion": test_step_conclusion},
        ],
    }


class TestFindSuspectedHangs:
    """#10010: cancelled-at-timeout jobs get their own verdict, not a retry."""

    def test_cancelled_at_timeout_with_unfinished_test_step_is_flagged(self) -> None:
        job = _cancelled_job()  # ~30m05s duration, test step conclusion=None

        findings = find_suspected_hangs(
            [job], timeout_minutes_by_job={"Tests": 30}, tolerance_seconds=90
        )

        assert len(findings) == 1
        finding = findings[0]
        assert finding["kind"] == "suspected_hang"
        assert finding["check"] == "Tests"
        assert finding["run_id"] == 555
        assert finding["pr_number"] == 42
        assert finding["unfinished_step"] == "Run tests with coverage"
        assert finding["timeout_minutes"] == 30

    def test_cancelled_early_is_not_flagged(self) -> None:
        # Cancelled 2 minutes in (e.g. a manual abort) — nowhere near the
        # 30-minute timeout, so this is a normal cancellation, not a hang.
        job = _cancelled_job(completed_at="2026-07-19T00:02:00Z")

        findings = find_suspected_hangs(
            [job], timeout_minutes_by_job={"Tests": 30}, tolerance_seconds=90
        )

        assert findings == []

    def test_failed_normally_is_not_flagged(self) -> None:
        job = _cancelled_job()
        job["conclusion"] = "failure"

        findings = find_suspected_hangs(
            [job], timeout_minutes_by_job={"Tests": 30}, tolerance_seconds=90
        )

        assert findings == []

    def test_cancelled_at_timeout_with_finished_test_step_is_not_flagged(self) -> None:
        # Killed at ~timeout, but the test step already reached a verdict
        # (e.g. cancelled during a later upload/cleanup step, or a
        # fail-fast sibling) — not the in-flight-hang signature.
        job = _cancelled_job(test_step_conclusion="success")

        findings = find_suspected_hangs(
            [job], timeout_minutes_by_job={"Tests": 30}, tolerance_seconds=90
        )

        assert findings == []

    def test_unknown_job_name_is_not_flagged(self) -> None:
        job = _cancelled_job(name="Some New Job")

        findings = find_suspected_hangs(
            [job], timeout_minutes_by_job={"Tests": 30}, tolerance_seconds=90
        )

        assert findings == []

    def test_missing_timestamps_are_not_flagged(self) -> None:
        job = _cancelled_job(started_at="", completed_at="")

        findings = find_suspected_hangs(
            [job], timeout_minutes_by_job={"Tests": 30}, tolerance_seconds=90
        )

        assert findings == []

    def test_fingerprint_distinguishes_hangs_by_run(self) -> None:
        a = finding_fingerprint(
            {"kind": "suspected_hang", "check": "Tests", "run_id": 555}
        )
        b = finding_fingerprint(
            {"kind": "suspected_hang", "check": "Tests", "run_id": 999}
        )
        assert a != b  # two distinct incidents on the same check both file


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


class TestSuspectedHangLoopWiring:
    """End-to-end: cancelled-at-timeout job -> filed issue with the
    bounded-local/Linux-container playbook, distinct from a retry (#10010).
    """

    def _write_workflow(self, repo_root: Path) -> None:
        workflows_dir = repo_root / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)
        (workflows_dir / "ci.yml").write_text(
            "jobs:\n  test:\n    name: Tests\n    timeout-minutes: 30\n"
        )

    def _run_seed(self, run_id: int, pr_number: int, created_at: str) -> dict:
        return {
            "id": run_id,
            "workflow": "CI",
            "conclusion": "cancelled",
            "created_at": created_at,
            "pr_number": pr_number,
        }

    @pytest.mark.asyncio
    async def test_suspected_hang_files_playbook_issue(self, tmp_path: Path) -> None:
        loop, prs = _make_loop(tmp_path)
        self._write_workflow(Path(loop._config.repo_root))
        prs.list_workflow_runs.return_value = [
            self._run_seed(555, 42, "2026-07-19T00:00:00Z")
        ]
        prs.get_workflow_run_jobs.return_value = [_cancelled_job()]

        result = await loop._do_work()

        assert result["filed"] == 1
        title, body = prs.create_issue.await_args.args[0:2]
        assert "suspected CI hang" in title
        assert "#9983" in body
        assert "#10002" in body
        assert "killpg" in body
        assert "Linux container" in body
        assert "do NOT" in body  # explicit anti-blind-retry directive
        assert prs.create_issue.await_args.kwargs["labels"] == ["hydraflow-find"]

    @pytest.mark.asyncio
    async def test_recurring_run_dedupes_but_new_incident_still_files(
        self, tmp_path: Path
    ) -> None:
        loop, prs = _make_loop(tmp_path)
        self._write_workflow(Path(loop._config.repo_root))

        prs.list_workflow_runs.return_value = [
            self._run_seed(555, 42, "2026-07-19T00:00:00Z")
        ]
        prs.get_workflow_run_jobs.return_value = [_cancelled_job()]
        first = await loop._do_work()
        second = await loop._do_work()  # same run seen again -> deduped

        # A DIFFERENT run on the SAME check is a distinct incident and
        # must file its own issue — the fingerprint must not swallow it.
        prs.list_workflow_runs.return_value = [
            self._run_seed(777, 43, "2026-07-19T01:00:00Z")
        ]
        prs.get_workflow_run_jobs.return_value = [
            _cancelled_job(run_id=777, pr_number=43)
        ]
        third = await loop._do_work()

        assert first["filed"] == 1
        assert second["filed"] == 0
        assert third["filed"] == 1
        assert prs.create_issue.await_count == 2

    @pytest.mark.asyncio
    async def test_no_workflow_file_means_no_finding(self, tmp_path: Path) -> None:
        # Timeout-minutes lookup fails closed: no .github/workflows means
        # no reference timeout, so the classifier can't confirm anything
        # and stays silent instead of guessing.
        loop, prs = _make_loop(tmp_path)
        prs.list_workflow_runs.return_value = [
            self._run_seed(555, 42, "2026-07-19T00:00:00Z")
        ]
        prs.get_workflow_run_jobs.return_value = [_cancelled_job()]

        result = await loop._do_work()

        assert result["filed"] == 0
        prs.create_issue.assert_not_awaited()


class TestGateHealthPerTickCap:
    @pytest.mark.asyncio
    async def test_overflow_folds_into_one_summary(self, tmp_path: Path) -> None:
        """#10777: >cap findings file `cap` issues + ONE summary issue."""
        loop, prs = _make_loop(tmp_path)
        cap = loop._config.gate_health_max_issues_per_tick
        findings = [
            {
                "kind": "born_broken",
                "check": f"Check-{i}",
                "failures": 5,
                "first_seen": "2026-07-01T00:00:00Z",
                "last_seen": "2026-07-19T00:00:00Z",
            }
            for i in range(cap + 2)
        ]

        filed = await loop._file_findings(findings)

        assert prs.create_issue.await_count == cap + 1
        assert filed == cap + 1
        summaries = [
            c.args[0]
            for c in prs.create_issue.await_args_list
            if "over per-tick filing cap" in c.args[0]
        ]
        assert len(summaries) == 1
