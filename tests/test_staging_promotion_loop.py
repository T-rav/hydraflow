"""Tests for StagingPromotionLoop."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import evidence_pack
import subprocess_util
from audit_chain import AuditChain
from base_background_loop import LoopDeps
from ci_sentinels import ci_timeout
from config import HydraFlowConfig
from events import EventBus, EventType
from evidence_pack import GAP_REPRO_MANIFEST, RECORD_TYPE_EVIDENCE_PACK
from execution import SimpleResult
from models import PRInfo
from repro_manifest import MANIFEST_HEADING, MANIFEST_SCHEMA, extract_manifest_block
from staging_promotion_loop import StagingPromotionLoop
from state import StateTracker
from subprocess_util import CreditExhaustedError
from tests.helpers import install_repo_merge_policy

#: The real CH-4 compiler, captured at import time (before the autouse fake
#: below patches the module attribute) for the CH-7→CH-4 round-trip test.
_REAL_COMPILE_EVIDENCE_PACK = evidence_pack.compile_evidence_pack


@pytest.fixture(autouse=True)
def _fake_evidence_compiler(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Keep the CH-4 compiler off the network for every promoted-path test;
    TestEvidencePackTrigger installs its own instrumented fake on top."""
    fake = AsyncMock(return_value=MagicMock(gap_count=0))
    monkeypatch.setattr(evidence_pack, "compile_evidence_pack", fake)
    return fake


@pytest.fixture(autouse=True)
def _fake_merged_pr_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the loop's raw-gh boundary off the network for every test with
    benign empty responses: no merged PRs (CH-4 reconcile + G1 observed-advance
    sweeps no-op, via the RAISING ``run_subprocess``), no staging check-runs
    (named-gate sensor NOT green) and unknown gap (promotion-health gap None) via
    the NON-RAISING ``run_subprocess_result``. Tests that exercise a specific read
    install their own fakes on top (``_install_gh_fake``)."""

    async def _default_run(*cmd: str, **_kwargs: object) -> str:
        if cmd[:3] == ("gh", "pr", "list"):
            return "[]"
        raise AssertionError(f"unexpected run_subprocess command: {cmd}")

    async def _default_result(*cmd: str, **_kwargs: object) -> SimpleResult:
        if cmd[:2] == ("gh", "api"):
            path = cmd[2] if len(cmd) > 2 else ""
            if "/check-runs" in path:
                return SimpleResult(stdout=json.dumps({"check_runs": []}), returncode=0)
            if "/compare/" in path:
                return SimpleResult(stdout="", returncode=0)
        raise AssertionError(f"unexpected run_subprocess_result command: {cmd}")

    monkeypatch.setattr(subprocess_util, "run_subprocess", _default_run)
    monkeypatch.setattr(subprocess_util, "run_subprocess_result", _default_result)


def _make_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HydraFlowConfig:
    monkeypatch.setenv("HYDRAFLOW_STAGING_PROMOTION_INTERVAL", "300")
    return HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
        data_root=tmp_path / "data",
    )


def _make_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    staging_enabled: bool = True,
    rc_cadence_hours: int = 4,
    open_promotion: PRInfo | None = None,
    ci_result: tuple[bool, str] = (True, "ok"),
    merge_result: bool = True,
    rc_has_diff: bool = True,
) -> tuple[StagingPromotionLoop, MagicMock]:
    monkeypatch.setenv(
        "HYDRAFLOW_STAGING_ENABLED", "true" if staging_enabled else "false"
    )
    monkeypatch.setenv("HYDRAFLOW_RC_CADENCE_HOURS", str(rc_cadence_hours))
    cfg = _make_cfg(tmp_path, monkeypatch)

    stop_event = asyncio.Event()

    async def _sleep(_s: float) -> None:  # instant sleep for tests
        return None

    loop_deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop_event,
        status_cb=MagicMock(),
        enabled_cb=lambda _n: True,
        sleep_fn=_sleep,
    )

    prs = MagicMock()
    prs.find_open_promotion_pr = AsyncMock(return_value=open_promotion)
    prs.wait_for_ci = AsyncMock(return_value=ci_result)
    prs.merge_promotion_pr = AsyncMock(return_value=merge_result)
    prs.post_comment = AsyncMock()
    prs.close_issue = AsyncMock()
    prs.create_rc_branch = AsyncMock(return_value="sha123")
    prs.branch_has_diff_from_main = AsyncMock(return_value=rc_has_diff)
    prs.create_promotion_pr = AsyncMock(return_value=42)
    prs.push_synthetic_commit = AsyncMock(return_value="synthetic-sha-rc")
    prs.create_issue = AsyncMock(return_value=1234)
    prs.list_rc_branches = AsyncMock(return_value=[])
    prs.delete_branch = AsyncMock(return_value=True)

    loop = StagingPromotionLoop(config=cfg, prs=prs, deps=loop_deps)
    return loop, prs


def _make_pr(number: int = 42, branch: str = "rc/2026-04-18-1200") -> PRInfo:
    return PRInfo(
        number=number,
        issue_number=0,
        branch=branch,
        url=f"https://github.com/o/r/pull/{number}",
        draft=False,
    )


class TestStagingDisabled:
    @pytest.mark.asyncio
    async def test_noop_when_staging_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch, staging_enabled=False)
        result = await loop._do_work()
        assert result == {"status": "staging_disabled"}
        prs.find_open_promotion_pr.assert_not_called()
        prs.create_rc_branch.assert_not_called()


class TestCadenceGate:
    @pytest.mark.asyncio
    async def test_no_op_when_cadence_not_elapsed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch, rc_cadence_hours=4)
        loop._record_last_rc(datetime.now(UTC) - timedelta(hours=1))
        result = await loop._do_work()
        assert result == {"status": "cadence_not_elapsed"}
        prs.create_rc_branch.assert_not_called()

    @pytest.mark.asyncio
    async def test_cuts_rc_when_cadence_elapsed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch, rc_cadence_hours=4)
        loop._record_last_rc(datetime.now(UTC) - timedelta(hours=5))
        result = await loop._do_work()
        assert result["status"] == "opened"
        assert result["pr"] == 42
        prs.create_rc_branch.assert_called_once()
        prs.create_promotion_pr.assert_called_once()
        # Workflow-trigger workaround for #8705: synthetic commit is pushed
        # AFTER PR creation so pull_request:synchronize fires the workflows
        # that pull_request:opened doesn't.
        prs.push_synthetic_commit.assert_called_once()
        rc_arg = prs.push_synthetic_commit.call_args.args[0]
        assert rc_arg.startswith("rc/")
        msg_arg = prs.push_synthetic_commit.call_args.args[1]
        assert "trigger CI" in msg_arg
        assert "(#42)" in msg_arg

    @pytest.mark.asyncio
    async def test_cuts_rc_on_first_run_no_timestamp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch)
        result = await loop._do_work()
        assert result["status"] == "opened"
        prs.create_rc_branch.assert_called_once()


class TestMissedCadenceBootCheck:
    """#10009: loud boot-time warning when the RC cadence was missed by a
    wide margin (factory process was likely down), distinct from the
    ordinary cadence gate which already cuts immediately once the plain
    cadence has elapsed."""

    @pytest.mark.asyncio
    async def test_no_marker_no_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        loop, _ = _make_loop(tmp_path, monkeypatch, rc_cadence_hours=4)
        assert not loop._cadence_path().exists()
        with caplog.at_level("WARNING", logger="hydraflow.staging_promotion_loop"):
            await loop._do_work()
        assert not any(
            "missed its RC cadence" in r.getMessage() for r in caplog.records
        )
        assert loop._boot_cadence_checked is True

    @pytest.mark.asyncio
    async def test_recent_marker_no_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        loop, _ = _make_loop(tmp_path, monkeypatch, rc_cadence_hours=4)
        loop._record_last_rc(datetime.now(UTC) - timedelta(hours=1))
        with caplog.at_level("WARNING", logger="hydraflow.staging_promotion_loop"):
            await loop._do_work()
        assert not any(
            "missed its RC cadence" in r.getMessage() for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_elapsed_but_below_alert_multiplier_no_loud_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """5h behind a 4h cadence already cuts (elapsed >= cadence) but is
        below the 1.5x=6h alert threshold — no loud "was likely down" log."""
        loop, prs = _make_loop(tmp_path, monkeypatch, rc_cadence_hours=4)
        loop._record_last_rc(datetime.now(UTC) - timedelta(hours=5))
        with caplog.at_level("WARNING", logger="hydraflow.staging_promotion_loop"):
            result = await loop._do_work()
        assert result["status"] == "opened"
        prs.create_rc_branch.assert_called_once()
        assert not any(
            "missed its RC cadence" in r.getMessage() for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_beyond_alert_multiplier_logs_loud_warning_and_cuts(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """20h behind a 4h cadence (>1.5x=6h) — loud warning AND immediate cut."""
        loop, prs = _make_loop(tmp_path, monkeypatch, rc_cadence_hours=4)
        loop._record_last_rc(datetime.now(UTC) - timedelta(hours=20))
        with caplog.at_level("WARNING", logger="hydraflow.staging_promotion_loop"):
            result = await loop._do_work()
        assert result["status"] == "opened"
        prs.create_rc_branch.assert_called_once()
        warnings = [
            r.getMessage()
            for r in caplog.records
            if "missed its RC cadence" in r.getMessage()
        ]
        assert len(warnings) == 1
        assert "cadence=4h" in warnings[0]
        assert "likely down" in warnings[0]

    @pytest.mark.asyncio
    async def test_only_warns_once_per_loop_lifetime(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        loop, _ = _make_loop(tmp_path, monkeypatch, rc_cadence_hours=4)
        loop._record_last_rc(datetime.now(UTC) - timedelta(hours=20))
        with caplog.at_level("WARNING", logger="hydraflow.staging_promotion_loop"):
            await loop._do_work()  # first tick: cuts an RC, records a fresh marker
            await loop._do_work()  # second tick: marker is now fresh, but even
            # if it weren't, the boot check must not fire twice
        warnings = [
            r for r in caplog.records if "missed its RC cadence" in r.getMessage()
        ]
        assert len(warnings) == 1


class TestRcBranchNaming:
    @pytest.mark.asyncio
    async def test_rc_branch_uses_prefix_and_timestamp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch)
        await loop._do_work()
        (branch,) = prs.create_rc_branch.call_args.args
        assert branch.startswith("rc/")
        # rc/YYYY-MM-DD-HHMM = 18 chars total
        assert len(branch) == len("rc/") + len("YYYY-MM-DD-HHMM")


class TestRecordOnCreate:
    @pytest.mark.asyncio
    async def test_records_timestamp_after_successful_creation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _ = _make_loop(tmp_path, monkeypatch)
        assert not loop._cadence_path().exists()
        await loop._do_work()
        assert loop._cadence_path().exists()

    @pytest.mark.asyncio
    async def test_does_not_record_when_rc_branch_creation_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch)
        prs.create_rc_branch.side_effect = RuntimeError("boom")
        result = await loop._do_work()
        assert result["status"] == "rc_branch_failed"
        assert not loop._cadence_path().exists()


class TestEmptyRcNoOp:
    @pytest.mark.asyncio
    async def test_skips_pr_when_rc_has_no_commits_ahead(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch, rc_has_diff=False)
        result = await loop._do_work()
        assert result["status"] == "no_commits"
        assert result["rc_branch"].startswith("rc/")
        prs.branch_has_diff_from_main.assert_called_once()
        # No promotion PR is opened and no synthetic commit is pushed —
        # avoids the "No commits between main and <rc>" GraphQL hard-fail.
        prs.create_promotion_pr.assert_not_called()
        prs.push_synthetic_commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_rc_logs_info_not_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        loop, _ = _make_loop(tmp_path, monkeypatch, rc_has_diff=False)
        with caplog.at_level("INFO", logger="hydraflow.staging_promotion_loop"):
            await loop._do_work()
        assert not any(r.levelname == "ERROR" for r in caplog.records)
        assert any(
            "no commits ahead" in r.getMessage() and r.levelname == "INFO"
            for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_empty_rc_records_cadence_to_avoid_immediate_recut(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _ = _make_loop(tmp_path, monkeypatch, rc_has_diff=False)
        assert not loop._cadence_path().exists()
        await loop._do_work()
        # Recording the timestamp prevents re-cutting an identical RC on the
        # very next poll tick during quiet periods.
        assert loop._cadence_path().exists()

    @pytest.mark.asyncio
    async def test_opens_pr_when_rc_has_commits_ahead(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch, rc_has_diff=True)
        result = await loop._do_work()
        assert result["status"] == "opened"
        assert result["pr"] == 42
        prs.create_promotion_pr.assert_called_once()
        prs.push_synthetic_commit.assert_called_once()


class TestOpenPromotionPassing:
    @pytest.mark.asyncio
    async def test_merges_on_green_ci(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(99),
            ci_result=(True, "ok"),
        )
        result = await loop._do_work()
        assert result == {"status": "promoted", "pr": 99}
        prs.merge_promotion_pr.assert_called_once_with(99, auto_rebase=True)
        prs.create_rc_branch.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_merge_failed_when_merge_rejects(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _ = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(99),
            ci_result=(True, "ok"),
            merge_result=False,
        )
        result = await loop._do_work()
        assert result == {"status": "merge_failed", "pr": 99}


class TestOpenPromotionFailing:
    @pytest.mark.asyncio
    async def test_closes_pr_on_ci_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(99),
            ci_result=(False, "ci failed: scenario tests"),
        )
        result = await loop._do_work()
        assert result == {"status": "ci_failed", "pr": 99, "find_issue": 1234}
        prs.post_comment.assert_called_once()
        prs.close_issue.assert_called_once_with(99)

    @pytest.mark.asyncio
    async def test_files_hydraflow_find_issue_on_ci_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(99),
            ci_result=(False, "scenario suite failed"),
        )
        await loop._do_work()
        prs.create_issue.assert_called_once()
        args, _kwargs = prs.create_issue.call_args
        title, body, labels = args
        # Stable title (no PR number) so one rolling issue dedups across ticks;
        # the PR number + failure summary live in the body (#9359).
        assert title == "RC promotion to main failing CI"
        assert "#99" in body
        assert "scenario suite failed" in body
        assert labels == ["hydraflow-find"]

    @pytest.mark.asyncio
    async def test_closes_pr_even_if_issue_filing_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(99),
            ci_result=(False, "boom"),
        )
        prs.create_issue.side_effect = RuntimeError("gh down")
        result = await loop._do_work()
        assert result == {"status": "ci_failed", "pr": 99, "find_issue": 0}
        prs.close_issue.assert_called_once_with(99)

    @pytest.mark.asyncio
    async def test_ci_pending_leaves_pr_open(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(99),
            # Verbatim sentinel from PRManager.wait_for_ci on timeout.
            ci_result=(False, "Timeout after 60s"),
        )
        result = await loop._do_work()
        assert result == {"status": "ci_pending", "pr": 99}
        prs.close_issue.assert_not_called()
        prs.merge_promotion_pr.assert_not_called()


class TestDefaultInterval:
    def test_returns_config_interval(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _ = _make_loop(tmp_path, monkeypatch)
        assert loop._get_default_interval() == 300


class TestRetentionSweep:
    def _iso(self, dt: datetime) -> str:
        return dt.isoformat().replace("+00:00", "Z")

    @pytest.mark.asyncio
    async def test_sweep_skipped_when_recently_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch)
        loop._sweep_path().parent.mkdir(parents=True, exist_ok=True)
        loop._sweep_path().write_text(datetime.now(UTC).isoformat())
        # Block other work paths so _do_work completes promptly.
        prs.find_open_promotion_pr.return_value = _make_pr(99)
        prs.wait_for_ci.return_value = (False, "Timed out")
        await loop._do_work()
        prs.list_rc_branches.assert_not_called()

    @pytest.mark.asyncio
    async def test_deletes_rc_branches_older_than_retention(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch)
        old = datetime.now(UTC) - timedelta(days=30)
        recent = datetime.now(UTC) - timedelta(days=2)
        prs.list_rc_branches.return_value = [
            ("rc/2026-03-10-1200", self._iso(old)),
            ("rc/2026-04-16-0800", self._iso(recent)),
        ]
        # Force _do_work straight into the sweep by making it cadence_not_elapsed.
        loop._record_last_rc(datetime.now(UTC))
        result = await loop._do_work()
        prs.delete_branch.assert_called_once_with("rc/2026-03-10-1200")
        assert result["swept"] == 1

    @pytest.mark.asyncio
    async def test_preserves_newest_even_if_past_retention(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch)
        # Every branch is older than retention (7d default); the newest should
        # still survive so the repo isn't left with zero RC snapshots.
        prs.list_rc_branches.return_value = [
            ("rc/2026-01-01-1200", self._iso(datetime.now(UTC) - timedelta(days=90))),
            ("rc/2026-01-10-1200", self._iso(datetime.now(UTC) - timedelta(days=80))),
        ]
        loop._record_last_rc(datetime.now(UTC))
        await loop._do_work()
        deleted_branches = [c.args[0] for c in prs.delete_branch.call_args_list]
        assert "rc/2026-01-10-1200" not in deleted_branches
        assert "rc/2026-01-01-1200" in deleted_branches

    @pytest.mark.asyncio
    async def test_preserves_branch_with_open_pr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        open_pr = _make_pr(99, branch="rc/2026-01-01-1200")
        loop, prs = _make_loop(tmp_path, monkeypatch, open_promotion=open_pr)
        prs.list_rc_branches.return_value = [
            ("rc/2026-01-01-1200", self._iso(datetime.now(UTC) - timedelta(days=90))),
            ("rc/2026-04-16-0800", self._iso(datetime.now(UTC) - timedelta(days=2))),
        ]
        prs.wait_for_ci.return_value = (False, "Timed out")
        await loop._do_work()
        deleted_branches = [c.args[0] for c in prs.delete_branch.call_args_list]
        assert "rc/2026-01-01-1200" not in deleted_branches

    @pytest.mark.asyncio
    async def test_records_sweep_timestamp_even_when_no_deletes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _ = _make_loop(tmp_path, monkeypatch)
        assert not loop._sweep_path().exists()
        loop._record_last_rc(datetime.now(UTC))
        await loop._do_work()
        assert loop._sweep_path().exists()


class TestStateWritesOnPromoted:
    @pytest.mark.asyncio
    async def test_writes_last_green_rc_sha_on_promoted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(number=77),
            ci_result=(True, "ok"),
            merge_result=True,
        )
        prs.get_pr_head_sha = AsyncMock(return_value="abc123deadbeef")
        state = StateTracker(state_file=tmp_path / "s.json")
        loop._state = state  # type: ignore[attr-defined]
        # seed a stale counter so reset is observable
        state.increment_auto_reverts_in_cycle()
        assert state.get_auto_reverts_in_cycle() == 1

        result = await loop._do_work()

        assert result["status"] == "promoted"
        assert state.get_last_green_rc_sha() == "abc123deadbeef"
        assert state.get_auto_reverts_in_cycle() == 0


class TestStateWritesOnCIFailed:
    @pytest.mark.asyncio
    async def test_writes_last_rc_red_sha_and_bumps_cycle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(number=88),
            ci_result=(False, "pytest failed: test_foo"),
        )
        prs.get_pr_head_sha = AsyncMock(return_value="cafef00d")
        state = StateTracker(state_file=tmp_path / "s.json")
        loop._state = state  # type: ignore[attr-defined]

        result = await loop._do_work()

        assert result["status"] == "ci_failed"
        assert state.get_last_rc_red_sha() == "cafef00d"
        assert state.get_rc_cycle_id() == 1

    @pytest.mark.asyncio
    async def test_no_state_write_on_ci_pending(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(number=89),
            ci_result=(False, "timed out waiting for checks"),
        )
        prs.get_pr_head_sha = AsyncMock(return_value="never_read")
        state = StateTracker(state_file=tmp_path / "s.json")
        loop._state = state  # type: ignore[attr-defined]

        result = await loop._do_work()

        assert result["status"] == "ci_pending"
        assert state.get_last_rc_red_sha() == ""
        assert state.get_rc_cycle_id() == 0


def _escalation_calls(prs: MagicMock) -> list:
    """create_issue calls whose labels include the rc-promotion-stuck escalation."""
    out = []
    for call in prs.create_issue.await_args_list:
        labels = call.kwargs.get("labels") or (
            call.args[2] if len(call.args) > 2 else []
        )
        if "rc-promotion-stuck" in labels:
            out.append(call)
    return out


class TestRepeatedFailureEscalation:
    """#9359 hardening: repeated RC-promotion failures escalate ONCE to a human
    so a multi-day pipeline stall (like #9219..#9342) can't pass unnoticed."""

    @pytest.mark.asyncio
    async def test_escalates_once_when_streak_hits_threshold(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_RC_CONSECUTIVE_FAILURE_ESCALATION_THRESHOLD", "2")
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(number=70),
            ci_result=(False, "ci failed: scenario tests"),
        )
        state = StateTracker(state_file=tmp_path / "s.json")
        loop._state = state  # type: ignore[attr-defined]

        # Two consecutive failing promotions reach the threshold.
        await loop._do_work()
        assert state.get_consecutive_rc_failures() == 1
        assert _escalation_calls(prs) == []  # not yet

        await loop._do_work()
        assert state.get_consecutive_rc_failures() == 2
        escalations = _escalation_calls(prs)
        assert len(escalations) == 1
        assert "hitl-escalation" in (
            escalations[0].kwargs.get("labels") or escalations[0].args[2]
        )

        # A third failure must NOT re-escalate (fires once per streak).
        await loop._do_work()
        assert state.get_consecutive_rc_failures() == 3
        assert len(_escalation_calls(prs)) == 1

    @pytest.mark.asyncio
    async def test_green_promotion_resets_the_streak(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(number=71),
            ci_result=(False, "boom"),
        )
        state = StateTracker(state_file=tmp_path / "s.json")
        loop._state = state  # type: ignore[attr-defined]

        await loop._do_work()
        assert state.get_consecutive_rc_failures() == 1

        # Next tick: CI is green and the promotion merges -> streak resets.
        prs.wait_for_ci.return_value = (True, "ok")
        prs.merge_promotion_pr = AsyncMock(return_value=True)
        prs.get_pr_head_sha = AsyncMock(return_value="greensha")
        result = await loop._do_work()

        assert result["status"] == "promoted"
        assert state.get_consecutive_rc_failures() == 0


class TestEscalationAutoClose:
    """#10015: the rc-promotion-stuck escalation must auto-close on the next
    green promotion — mirroring the rc_ci rolling-issue pattern. Before this,
    the escalation was filed via bare ``create_issue`` with no resolve path:
    a green promotion only reset the failure counter, and #9867 closed only
    because an unrelated PR body happened to say "Closes #9867"."""

    ESCALATION_ISSUE = 8002
    RC_CI_ISSUE = 7001

    def _streak_loop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[StagingPromotionLoop, MagicMock, StateTracker]:
        monkeypatch.setenv("HYDRAFLOW_RC_CONSECUTIVE_FAILURE_ESCALATION_THRESHOLD", "2")
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(number=70),
            ci_result=(False, "ci failed: scenario tests"),
        )

        async def _create_issue(title: str, body: str, labels: list[str]) -> int:
            if "rc-promotion-stuck" in labels:
                return self.ESCALATION_ISSUE
            return self.RC_CI_ISSUE

        prs.create_issue = AsyncMock(side_effect=_create_issue)
        prs.update_issue_body = AsyncMock()
        prs.get_pr_head_sha = AsyncMock(return_value="somesha")
        state = StateTracker(state_file=tmp_path / "s.json")
        loop._state = state  # type: ignore[attr-defined]
        return loop, prs, state

    @pytest.mark.asyncio
    async def test_escalation_is_tracked_as_rollup_subject(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, state = self._streak_loop(tmp_path, monkeypatch)

        await loop._do_work()  # failure 1 — below threshold
        assert state.get_rollup_issue("staging_promotion:rc_promotion_stuck") is None

        await loop._do_work()  # failure 2 — escalates, tracked as a rollup
        tracked = state.get_rollup_issue("staging_promotion:rc_promotion_stuck")
        assert tracked is not None
        assert tracked["issue_number"] == self.ESCALATION_ISSUE

    @pytest.mark.asyncio
    async def test_escalation_title_is_stable_and_count_lives_in_body(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rollup contract: variable content (streak size, latest PR) goes in
        the BODY; the title must be stable so re-adoption dedup works."""
        loop, prs, _state = self._streak_loop(tmp_path, monkeypatch)

        await loop._do_work()
        await loop._do_work()

        escalations = _escalation_calls(prs)
        assert len(escalations) == 1
        title, body, labels = escalations[0].args
        assert "promotion stuck" in title
        assert "2" not in title  # streak count must NOT be in the title
        assert "2 times in a row" in body
        assert "#70" in body
        assert "hitl-escalation" in labels
        assert "rc-promotion-stuck" in labels

    @pytest.mark.asyncio
    async def test_green_promotion_auto_closes_open_escalation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, state = self._streak_loop(tmp_path, monkeypatch)

        await loop._do_work()
        await loop._do_work()  # escalation filed + tracked

        prs.wait_for_ci.return_value = (True, "ok")
        prs.merge_promotion_pr = AsyncMock(return_value=True)
        result = await loop._do_work()

        assert result["status"] == "promoted"
        prs.close_issue.assert_any_await(self.ESCALATION_ISSUE)
        assert state.get_rollup_issue("staging_promotion:rc_promotion_stuck") is None
        assert state.get_consecutive_rc_failures() == 0

    @pytest.mark.asyncio
    async def test_green_without_open_escalation_is_a_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """resolve() is idempotent — a clean green tick with no tracked
        escalation must not touch GitHub for the escalation subject."""
        loop, prs, _state = self._streak_loop(tmp_path, monkeypatch)
        prs.wait_for_ci.return_value = (True, "ok")
        prs.merge_promotion_pr = AsyncMock(return_value=True)

        result = await loop._do_work()

        assert result["status"] == "promoted"
        prs.close_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fresh_streak_after_green_files_new_escalation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, _state = self._streak_loop(tmp_path, monkeypatch)

        await loop._do_work()
        await loop._do_work()  # streak 1 escalates
        assert len(_escalation_calls(prs)) == 1

        prs.wait_for_ci.return_value = (True, "ok")
        prs.merge_promotion_pr = AsyncMock(return_value=True)
        await loop._do_work()  # green — closes + clears tracking

        prs.wait_for_ci.return_value = (False, "ci failed: scenario tests")
        await loop._do_work()
        await loop._do_work()  # streak 2 escalates fresh

        assert len(_escalation_calls(prs)) == 2


class TestSentinelFidelity:
    @pytest.mark.asyncio
    async def test_producer_timeout_sentinel_is_pending_not_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Feed the loop the EXACT symbol pr_manager.wait_for_ci emits on timeout
        (ci_timeout) — it must classify as pending, never a failure. Couples the
        consumer to the real producer string, not a hand-written literal."""
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(number=72),
            ci_result=(False, ci_timeout(60)),
        )
        state = StateTracker(state_file=tmp_path / "s.json")
        loop._state = state  # type: ignore[attr-defined]

        result = await loop._do_work()

        # ci_pending, never a failure classification (no find_issue filed). The
        # promotion-health signal (piece b) rides alongside on any operating tick.
        assert result["status"] == "ci_pending"
        assert result["pr"] == 72
        assert "find_issue" not in result
        prs.close_issue.assert_not_called()
        assert state.get_consecutive_rc_failures() == 0
        assert _escalation_calls(prs) == []


class TestRollingFailureIssue:
    """#9359 issue-hygiene: one rolling 'promotion CI failing' issue, auto-closed
    on the next green promotion (replaces the per-PR pile-up #9219..#9342)."""

    @pytest.mark.asyncio
    async def test_red_then_green_files_one_issue_and_auto_closes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(number=99),
            ci_result=(False, "boom"),
        )
        prs.create_issue = AsyncMock(return_value=7001)
        prs.update_issue_body = AsyncMock()
        state = StateTracker(state_file=tmp_path / "s.json")
        loop._state = state  # type: ignore[attr-defined]

        # Red tick: files exactly ONE rolling issue, tracked in state.
        r1 = await loop._do_work()
        assert r1["status"] == "ci_failed"
        prs.create_issue.assert_awaited_once()
        assert state.get_rollup_issue("staging_promotion:rc_ci")["issue_number"] == 7001

        # Second red tick (same body) must NOT file a new issue.
        await loop._do_work()
        prs.create_issue.assert_awaited_once()

        # Green tick: promotion succeeds → the rolling issue auto-closes.
        prs.wait_for_ci.return_value = (True, "ok")
        prs.merge_promotion_pr = AsyncMock(return_value=True)
        prs.get_pr_head_sha = AsyncMock(return_value="greensha")
        r2 = await loop._do_work()

        assert r2["status"] == "promoted"
        prs.close_issue.assert_any_await(7001)
        assert state.get_rollup_issue("staging_promotion:rc_ci") is None


class TestEvidencePackTrigger:
    """CH-4 (#9732): the release evidence pack compiles after a successful
    promotion — compile-only, report-only, fail-open."""

    RC_BRANCH = "rc/2026-07-08-1200"

    def _promoted_loop(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        merge_result: bool = True,
        ci_result: tuple[bool, str] = (True, "ok"),
    ) -> tuple[StagingPromotionLoop, MagicMock]:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(99, branch=self.RC_BRANCH),
            ci_result=ci_result,
            merge_result=merge_result,
        )
        prs.get_pr_head_sha = AsyncMock(return_value="headsha")
        return loop, prs

    def _install_compiler(
        self, monkeypatch: pytest.MonkeyPatch, error: Exception | None = None
    ) -> list[tuple]:
        calls: list[tuple] = []

        async def _fake(config, rc_branch, pr_number, *, disabled_workers=None):
            calls.append((rc_branch, pr_number, disabled_workers))
            if error is not None:
                raise error
            return MagicMock(gap_count=0)

        monkeypatch.setattr(evidence_pack, "compile_evidence_pack", _fake)
        return calls

    def _alerts(self, queue) -> list:
        alerts = []
        while not queue.empty():
            event = queue.get_nowait()
            if event.type is EventType.SYSTEM_ALERT:
                alerts.append(event)
        return alerts

    @pytest.mark.asyncio
    async def test_compiles_pack_after_successful_promotion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._install_compiler(monkeypatch)
        loop, _ = self._promoted_loop(tmp_path, monkeypatch)

        result = await loop._do_work()

        assert result == {"status": "promoted", "pr": 99}
        assert calls == [(self.RC_BRANCH, 99, None)]  # stateless → gap, not guess

    @pytest.mark.asyncio
    async def test_passes_disabled_workers_from_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._install_compiler(monkeypatch)
        loop, _ = self._promoted_loop(tmp_path, monkeypatch)
        state = StateTracker(state_file=tmp_path / "s.json")
        state.set_disabled_workers({"sentry"})
        loop._state = state  # type: ignore[attr-defined]

        await loop._do_work()

        assert calls == [(self.RC_BRANCH, 99, {"sentry"})]

    @pytest.mark.asyncio
    async def test_not_compiled_when_merge_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._install_compiler(monkeypatch)
        loop, _ = self._promoted_loop(tmp_path, monkeypatch, merge_result=False)

        result = await loop._do_work()

        assert result == {"status": "merge_failed", "pr": 99}
        assert calls == []

    @pytest.mark.asyncio
    async def test_not_compiled_on_ci_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._install_compiler(monkeypatch)
        loop, _ = self._promoted_loop(tmp_path, monkeypatch, ci_result=(False, "boom"))

        result = await loop._do_work()

        assert result["status"] == "ci_failed"
        assert calls == []

    @pytest.mark.asyncio
    async def test_kill_switch_disables_compilation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_EVIDENCE_PACK_ENABLED", "false")
        calls = self._install_compiler(monkeypatch)
        loop, _ = self._promoted_loop(tmp_path, monkeypatch)

        result = await loop._do_work()

        assert result == {"status": "promoted", "pr": 99}
        assert calls == []

    @pytest.mark.asyncio
    async def test_compiler_failure_is_fail_open_and_alerts(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        self._install_compiler(monkeypatch, error=RuntimeError("disk full"))
        loop, _ = self._promoted_loop(tmp_path, monkeypatch)
        queue = loop._bus.subscribe()

        with caplog.at_level("WARNING", logger="hydraflow.staging_promotion_loop"):
            result = await loop._do_work()

        assert result == {"status": "promoted", "pr": 99}  # NEVER blocks promotion
        assert any("vidence" in r.getMessage() for r in caplog.records)
        alerts = self._alerts(queue)
        assert len(alerts) == 1
        assert alerts[0].data["source"] == "evidence_pack"
        assert "#99" in alerts[0].data["message"]

    @pytest.mark.asyncio
    async def test_failure_alert_is_deduped_per_rc(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._install_compiler(monkeypatch, error=RuntimeError("still broken"))
        loop, _ = self._promoted_loop(tmp_path, monkeypatch)
        queue = loop._bus.subscribe()

        await loop._do_work()
        await loop._do_work()  # same RC promoted-tick shape again

        assert len(self._alerts(queue)) == 1

    @pytest.mark.asyncio
    async def test_credit_exhaustion_propagates_not_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._install_compiler(monkeypatch, error=CreditExhaustedError("billing cap"))
        loop, _ = self._promoted_loop(tmp_path, monkeypatch)

        with pytest.raises(CreditExhaustedError):
            await loop._do_work()


class TestMergePolicyGateOnPromotion:
    """CH-3 (#9731) — the policy gate at the RC promotion seam."""

    @pytest.mark.asyncio
    async def test_policy_deny_leaves_promotion_pr_open(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _run(*cmd, **_kwargs):
            if cmd[:3] == ("gh", "pr", "list"):
                return "[]"  # CH-4 reconcile sweep: nothing merged
            assert cmd[:3] == ("gh", "pr", "view")
            return json.dumps({"labels": []})

        monkeypatch.setattr(subprocess_util, "run_subprocess", _run)

        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(99),
            ci_result=(True, "ok"),
        )
        install_repo_merge_policy(loop._config)
        prs.get_pr_diff_names = AsyncMock(return_value=["src/app.py"])

        result = await loop._do_work()

        assert result == {"status": "policy_denied", "pr": 99}
        prs.merge_promotion_pr.assert_not_called()
        comment = prs.post_comment.await_args.args[1]
        assert "Blocked by merge policy" in comment
        assert "policy-override:" in comment

    async def test_policy_deny_emits_system_alert(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A blocked RC promotion must be LOUD (review finding): every
        cadence tick silently blocking is an operator-invisible outage —
        the deny publishes a SYSTEM_ALERT like the other policy seams."""

        async def _run(*cmd, **_kwargs):
            if cmd[:3] == ("gh", "pr", "list"):
                return "[]"  # CH-4 reconcile sweep: nothing merged
            assert cmd[:3] == ("gh", "pr", "view")
            return json.dumps({"labels": []})

        monkeypatch.setattr(subprocess_util, "run_subprocess", _run)

        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(99),
            ci_result=(True, "ok"),
        )
        install_repo_merge_policy(loop._config)
        prs.get_pr_diff_names = AsyncMock(return_value=["src/app.py"])
        queue = loop._bus.subscribe()

        result = await loop._do_work()

        assert result == {"status": "policy_denied", "pr": 99}
        alerts = []
        while not queue.empty():
            event = queue.get_nowait()
            if event.type is EventType.SYSTEM_ALERT:
                alerts.append(event)
        assert len(alerts) == 1
        assert alerts[0].data["source"] == "merge_policy"
        assert "#99" in alerts[0].data["message"]

    @pytest.mark.asyncio
    async def test_default_policy_allows_rc_promotion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The packaged policy accepts the ADR-0042 promotion-lane grant."""
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(99),
            ci_result=(True, "ok"),
        )
        result = await loop._do_work()
        assert result == {"status": "promoted", "pr": 99}
        prs.merge_promotion_pr.assert_called_once_with(99, auto_rebase=True)


def _drain_alerts(queue) -> list:
    """Drain *queue* and return the SYSTEM_ALERT events it held."""
    alerts = []
    while not queue.empty():
        event = queue.get_nowait()
        if event.type is EventType.SYSTEM_ALERT:
            alerts.append(event)
    return alerts


class TestRcBodyReproManifest:
    """CH-7 gap (convergence review): the RC promotion PR body is the exact
    document CH-4's evidence-pack compiler reads the reproducibility manifest
    back from (``_rc_repro_manifest``). ``_cut_new_rc`` built its body inline
    and never passed it through ``repro_manifest.append_manifest``, so EVERY
    compiled binder recorded GAP_REPRO_MANIFEST — a guaranteed false gap."""

    @pytest.mark.asyncio
    async def test_promotion_pr_body_carries_parseable_manifest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(tmp_path, monkeypatch)

        result = await loop._do_work()

        assert result["status"] == "opened"
        body = prs.create_promotion_pr.call_args.kwargs["body"]
        # The original promotion prose must survive the append.
        assert "Automated release-candidate promotion PR." in body
        assert "ADR-0042" in body
        # Parse the manifest back with the same parser CH-4 uses.
        parsed = extract_manifest_block(body)
        assert parsed is not None
        assert parsed["schema"] == MANIFEST_SCHEMA
        assert set(parsed) >= {"hydraflow_sha", "models", "config_snapshot"}

    @pytest.mark.asyncio
    async def test_manifest_failure_still_cuts_rc_fail_open(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A manifest error must never block the RC cut (evidence, not
        load-bearing — same fail-open contract as pr_manager.create_pr)."""
        monkeypatch.setattr(
            "repro_manifest.build_manifest",
            MagicMock(side_effect=RuntimeError("hash boom")),
        )
        loop, prs = _make_loop(tmp_path, monkeypatch)

        result = await loop._do_work()

        assert result["status"] == "opened"
        prs.create_promotion_pr.assert_called_once()
        body = prs.create_promotion_pr.call_args.kwargs["body"]
        assert MANIFEST_HEADING not in body
        assert "Automated release-candidate promotion PR." in body

    @pytest.mark.asyncio
    async def test_cut_rc_body_round_trips_into_pack_without_manifest_gap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end CH-7→CH-4: the body ``_cut_new_rc`` writes is the body
        the REAL compiler parses — the pack must carry a parsed
        ``repro_manifest`` and NO GAP_REPRO_MANIFEST entry."""
        monkeypatch.setattr(
            evidence_pack, "compile_evidence_pack", _REAL_COMPILE_EVIDENCE_PACK
        )
        loop, prs = _make_loop(tmp_path, monkeypatch)

        # Tick 1: cut the RC and capture the body the loop actually wrote.
        cut = await loop._do_work()
        assert cut["status"] == "opened"
        rc_branch = cut["rc_branch"]
        body = prs.create_promotion_pr.call_args.kwargs["body"]

        # Tick 2: that PR is now the open promotion, CI is green, and gh
        # serves the SAME body back to the compiler.
        async def _fake_gh(*cmd: str, **_kwargs: object) -> str:
            if cmd[:3] == ("gh", "pr", "list"):
                return "[]"  # reconcile sweep: nothing else merged
            assert cmd[:3] == ("gh", "pr", "view"), cmd
            if int(cmd[3]) == 42:
                return json.dumps(
                    {
                        "number": 42,
                        "title": f"Promote {rc_branch} → main",
                        "url": "https://github.com/o/r/pull/42",
                        "body": body,
                        "author": {"login": "hydra-ops-bot"},
                        "baseRefName": "main",
                        "headRefName": rc_branch,
                        "headRefOid": "a" * 40,
                        "mergeCommit": {"oid": "b" * 40},
                        "mergedAt": "2026-07-09T00:00:00Z",
                        "commits": [
                            {
                                "oid": "c" * 40,
                                "messageHeadline": "feat(z): one change (#9001)",
                            }
                        ],
                    }
                )
            return json.dumps(
                {
                    "number": int(cmd[3]),
                    "title": f"PR {cmd[3]}",
                    "body": "Closes #1.",
                    "author": {"login": "agent-z"},
                }
            )

        monkeypatch.setattr(subprocess_util, "run_subprocess", _fake_gh)
        prs.find_open_promotion_pr.return_value = _make_pr(42, branch=rc_branch)
        prs.get_pr_head_sha = AsyncMock(return_value="headsha")

        promoted = await loop._do_work()

        assert promoted["status"] == "promoted"
        pack_dir = loop._config.evidence_dir / rc_branch.replace("/", "-")
        manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["repro_manifest"] is not None
        assert manifest["repro_manifest"]["schema"] == MANIFEST_SCHEMA
        assert GAP_REPRO_MANIFEST not in {g["kind"] for g in manifest["gaps"]}


class TestReconcileMissingPacks:
    """CH-4 hardening (convergence review): ``_compile_evidence_pack`` only
    ran when THIS loop's own ``merge_promotion_pr`` returned True. An RC
    merged by any other actor (operator force-merge, Monitor-driven merge, a
    merge that landed after our call reported failure) got NO pack, no
    chained record, no gap entry, no alert — a silent missing binder. The
    reconcile sweep reads gh's merged list against the evidence stream."""

    RC_BRANCH = "rc/2026-07-08-0800"

    def _quiet_loop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[StagingPromotionLoop, MagicMock]:
        """A loop whose tick does no promotion work (cadence not elapsed)."""
        loop, prs = _make_loop(tmp_path, monkeypatch)
        loop._record_last_rc(datetime.now(UTC))
        return loop, prs

    def _install_gh_list(
        self,
        monkeypatch: pytest.MonkeyPatch,
        payload: list[dict] | Exception,
    ) -> list[tuple[str, ...]]:
        calls: list[tuple[str, ...]] = []

        async def _fake(*cmd: str, **_kwargs: object) -> str:
            calls.append(cmd)
            if isinstance(payload, Exception):
                raise payload
            assert cmd[:3] == ("gh", "pr", "list"), cmd
            assert "merged" in cmd  # only merged PRs are ever scanned
            return json.dumps(payload)

        monkeypatch.setattr(subprocess_util, "run_subprocess", _fake)
        return calls

    def _seed_pack_record(
        self, loop: StagingPromotionLoop, pr_number: int, rc_branch: str
    ) -> None:
        AuditChain(loop._config.evidence_packs_path).append(
            {
                "record_type": RECORD_TYPE_EVIDENCE_PACK,
                "pr_number": pr_number,
                "rc_branch": rc_branch,
            }
        )

    @pytest.mark.asyncio
    async def test_operator_merged_rc_gets_pack_on_next_tick(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        _fake_evidence_compiler: AsyncMock,
    ) -> None:
        self._install_gh_list(
            monkeypatch,
            [
                {"number": 555, "headRefName": self.RC_BRANCH},
                {"number": 554, "headRefName": "feature/not-an-rc"},
            ],
        )
        loop, _ = self._quiet_loop(tmp_path, monkeypatch)

        result = await loop._do_work()

        assert result["status"] == "cadence_not_elapsed"
        assert result["packs_reconciled"] == 1
        _fake_evidence_compiler.assert_awaited_once()
        args = _fake_evidence_compiler.await_args.args
        assert args[1:] == (self.RC_BRANCH, 555)  # (config, rc_branch, pr)

    @pytest.mark.asyncio
    async def test_already_packed_rcs_are_skipped_idempotently(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        _fake_evidence_compiler: AsyncMock,
    ) -> None:
        """A recorded RC is never re-compiled (no duplicate chain records);
        only the genuinely missing one is."""
        self._install_gh_list(
            monkeypatch,
            [
                {"number": 555, "headRefName": self.RC_BRANCH},
                {"number": 556, "headRefName": "rc/2026-07-08-1200"},
            ],
        )
        loop, _ = self._quiet_loop(tmp_path, monkeypatch)
        self._seed_pack_record(loop, 555, self.RC_BRANCH)

        result = await loop._do_work()

        assert result["packs_reconciled"] == 1
        _fake_evidence_compiler.assert_awaited_once()
        assert _fake_evidence_compiler.await_args.args[1:] == (
            "rc/2026-07-08-1200",
            556,
        )

    @pytest.mark.asyncio
    async def test_reconcile_is_idempotent_across_ticks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Once the compiler has chained its record, the next tick's sweep
        must not compile the same RC again."""
        compile_calls: list[int] = []

        async def _recording_compiler(config, rc_branch, pr_number, **_kwargs):
            compile_calls.append(pr_number)
            AuditChain(config.evidence_packs_path).append(
                {
                    "record_type": RECORD_TYPE_EVIDENCE_PACK,
                    "pr_number": pr_number,
                    "rc_branch": rc_branch,
                }
            )
            return MagicMock(gap_count=0)

        monkeypatch.setattr(evidence_pack, "compile_evidence_pack", _recording_compiler)
        self._install_gh_list(
            monkeypatch, [{"number": 555, "headRefName": self.RC_BRANCH}]
        )
        loop, _ = self._quiet_loop(tmp_path, monkeypatch)

        await loop._do_work()
        await loop._do_work()

        assert compile_calls == [555]
        stream = loop._config.evidence_packs_path.read_text(encoding="utf-8")
        assert len(stream.splitlines()) == 1

    @pytest.mark.asyncio
    async def test_kill_switch_off_means_no_sweep(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        _fake_evidence_compiler: AsyncMock,
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_EVIDENCE_PACK_ENABLED", "false")
        calls = self._install_gh_list(
            monkeypatch, [{"number": 555, "headRefName": self.RC_BRANCH}]
        )
        loop, _ = self._quiet_loop(tmp_path, monkeypatch)

        result = await loop._do_work()

        assert calls == []  # not even the gh listing runs when switched off
        assert "packs_reconciled" not in result
        _fake_evidence_compiler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_dry_run_means_no_sweep(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        _fake_evidence_compiler: AsyncMock,
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DRY_RUN", "true")
        calls = self._install_gh_list(
            monkeypatch, [{"number": 555, "headRefName": self.RC_BRANCH}]
        )
        loop, _ = self._quiet_loop(tmp_path, monkeypatch)

        result = await loop._do_work()

        assert calls == []
        assert "packs_reconciled" not in result
        _fake_evidence_compiler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sweep_failure_is_fail_open(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        self._install_gh_list(monkeypatch, RuntimeError("gh: 502"))
        loop, _ = self._quiet_loop(tmp_path, monkeypatch)

        with caplog.at_level("WARNING", logger="hydraflow.staging_promotion_loop"):
            result = await loop._do_work()

        assert result["status"] == "cadence_not_elapsed"
        assert "packs_reconciled" not in result
        assert any("reconcile" in r.getMessage().lower() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_sweep_failure_never_affects_promotion_work(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The tick's promotion result survives a broken sweep untouched."""
        self._install_gh_list(monkeypatch, RuntimeError("gh: 502"))
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(99),
            ci_result=(True, "ok"),
        )

        result = await loop._do_work()

        assert result == {"status": "promoted", "pr": 99}
        prs.merge_promotion_pr.assert_called_once_with(99, auto_rebase=True)

    @pytest.mark.asyncio
    async def test_sweep_credit_exhaustion_propagates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """dark-factory §2.2: the fail-open guard must re-raise billing
        signals, never burn ticks against an exhausted account."""
        self._install_gh_list(monkeypatch, CreditExhaustedError("billing cap"))
        loop, _ = self._quiet_loop(tmp_path, monkeypatch)

        with pytest.raises(CreditExhaustedError):
            await loop._do_work()


class TestPolicyDenyDedup:
    """CH-3 hardening (convergence review): the deny path posted the
    "Blocked by merge policy" comment AND a SYSTEM_ALERT unconditionally on
    EVERY promotion tick. With a corrupt policy.yaml (the designed
    fail-closed state) the open RC PR accumulated duplicate comments + alert
    spam every 300s until an operator fixed the policy. One comment + one
    alert per (PR, deny reason-class); a later allow verdict re-arms."""

    def _denied_loop(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        pr_number: int = 99,
        policy_text: str | None = None,
    ) -> tuple[StagingPromotionLoop, MagicMock]:
        async def _run(*cmd: str, **_kwargs: object) -> str:
            if cmd[:3] == ("gh", "pr", "list"):
                return "[]"  # CH-4 reconcile sweep: nothing merged
            assert cmd[:3] == ("gh", "pr", "view"), cmd
            return json.dumps({"labels": []})

        monkeypatch.setattr(subprocess_util, "run_subprocess", _run)
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(pr_number),
            ci_result=(True, "ok"),
        )
        if policy_text is None:
            install_repo_merge_policy(loop._config)
        else:
            install_repo_merge_policy(loop._config, text=policy_text)
        prs.get_pr_diff_names = AsyncMock(return_value=["src/app.py"])
        return loop, prs

    @pytest.mark.asyncio
    async def test_repeated_deny_alerts_and_comments_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = self._denied_loop(tmp_path, monkeypatch)
        queue = loop._bus.subscribe()

        r1 = await loop._do_work()
        r2 = await loop._do_work()

        assert r1 == r2 == {"status": "policy_denied", "pr": 99}
        assert len(_drain_alerts(queue)) == 1
        assert prs.post_comment.await_count == 1
        assert "Blocked by merge policy" in prs.post_comment.await_args.args[1]

    @pytest.mark.asyncio
    async def test_corrupt_policy_fail_closed_denies_are_deduped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The designed fail-closed state (unloadable policy.yaml) is exactly
        the standing-deny shape that was spamming — it must dedup too."""
        loop, prs = self._denied_loop(
            tmp_path, monkeypatch, policy_text="{{ not valid yaml !!"
        )
        queue = loop._bus.subscribe()

        r1 = await loop._do_work()
        r2 = await loop._do_work()

        assert r1 == r2 == {"status": "policy_denied", "pr": 99}
        alerts = _drain_alerts(queue)
        assert len(alerts) == 1
        assert "failing closed" in alerts[0].data["message"]
        assert prs.post_comment.await_count == 1

    @pytest.mark.asyncio
    async def test_deny_then_allow_rearms_so_a_new_deny_realerts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = self._denied_loop(tmp_path, monkeypatch)
        policy_path = (
            loop._config.repo_root
            / "docs"
            / "standards"
            / "factory_autonomy"
            / "policy.yaml"
        )
        queue = loop._bus.subscribe()

        await loop._do_work()  # deny → alert 1
        await loop._do_work()  # deny → deduped
        # Policy fixed: the packaged default allows. Merge fails, so the
        # same PR stays the open promotion for the next tick.
        policy_path.unlink()
        prs.merge_promotion_pr = AsyncMock(return_value=False)
        r3 = await loop._do_work()
        assert r3 == {"status": "merge_failed", "pr": 99}
        # Policy broken again: a NEW distinct deny event must re-alert.
        install_repo_merge_policy(loop._config)
        r4 = await loop._do_work()

        assert r4 == {"status": "policy_denied", "pr": 99}
        assert len(_drain_alerts(queue)) == 2
        assert prs.post_comment.await_count == 2

    @pytest.mark.asyncio
    async def test_different_pr_gets_a_fresh_alert(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = self._denied_loop(tmp_path, monkeypatch, pr_number=99)
        queue = loop._bus.subscribe()

        await loop._do_work()  # deny #99 → alert 1
        await loop._do_work()  # deny #99 → deduped
        prs.find_open_promotion_pr.return_value = _make_pr(100)
        r3 = await loop._do_work()  # deny #100 → fresh alert

        assert r3 == {"status": "policy_denied", "pr": 100}
        alerts = _drain_alerts(queue)
        assert len(alerts) == 2
        assert "#100" in alerts[1].data["message"]
        assert prs.post_comment.await_count == 2
        commented_prs = [c.args[0] for c in prs.post_comment.await_args_list]
        assert commented_prs == [99, 100]


_DEFAULT_CHECK_RUN_STARTED = "2026-07-23T00:00:00Z"


def _write_canonical(repo_root: Path, contexts: list[str]) -> None:
    """Materialize the canonical ``main`` ruleset the named-gate sensor reads.

    ``_staging_ci_is_green`` resolves the required-on-RC gate NAMES from
    ``branch_protection_audit.load_canonical`` (the on-disk contract at
    ``<repo_root>/docs/standards/branch_protection``), so tests that exercise a
    green sensor must write it under the config's ``repo_root`` (== tmp_path)."""
    canonical_dir = repo_root / "docs" / "standards" / "branch_protection"
    canonical_dir.mkdir(parents=True, exist_ok=True)
    (canonical_dir / "main_ruleset.json").write_text(
        json.dumps(
            {
                "name": "main protect",
                "target": "branch",
                "rules": [
                    {
                        "type": "required_status_checks",
                        "parameters": {
                            "required_status_checks": [{"context": c} for c in contexts]
                        },
                    }
                ],
            }
        )
    )
    (canonical_dir / "staging_ruleset.json").write_text(
        json.dumps({"name": "staging protect", "target": "branch", "rules": []})
    )


def _install_gh_fake(
    monkeypatch: pytest.MonkeyPatch,
    *,
    merged_prs: list[dict] | None = None,
    staging_gates: dict[str, str] | None = None,
    gap: int | None = None,
) -> None:
    """Route the loop's raw-gh reads used by the G1 (#10353) paths:

    - ``gh pr list`` (merged RC promotion PRs, ``_list_merged_promotion_prs``)
    - ``gh api .../commits/{staging}/check-runs`` (named-gate conclusions on
      staging HEAD, ``_staging_head_check_conclusions``)
    - ``gh api compare`` (``main..staging`` gap, ``_main_staging_gap``)

    Overrides the module autouse ``_fake_merged_pr_listing`` (last setattr wins).
    ``gh pr list`` goes through the RAISING ``run_subprocess``; the check-runs and
    compare reads go through the NON-RAISING ``run_subprocess_result``.
    *staging_gates* maps ``check-name -> conclusion``; *gap* is the compare
    ``ahead_by`` (``None`` => empty body, so the gap reads back as unknown).
    """
    check_runs = [
        {
            "name": name,
            "conclusion": conclusion,
            "started_at": _DEFAULT_CHECK_RUN_STARTED,
        }
        for name, conclusion in (staging_gates or {}).items()
    ]

    async def _run(*cmd: str, **_kwargs: object) -> str:
        if cmd[:3] == ("gh", "pr", "list"):
            return json.dumps(merged_prs or [])
        raise AssertionError(f"unexpected run_subprocess command: {cmd}")

    async def _result(*cmd: str, **_kwargs: object) -> SimpleResult:
        if cmd[:2] == ("gh", "api"):
            path = cmd[2] if len(cmd) > 2 else ""
            if "/check-runs" in path:
                return SimpleResult(
                    stdout=json.dumps({"check_runs": check_runs}), returncode=0
                )
            if "/compare/" in path:
                return SimpleResult(
                    stdout="" if gap is None else str(gap), returncode=0
                )
        raise AssertionError(f"unexpected run_subprocess_result command: {cmd}")

    monkeypatch.setattr(subprocess_util, "run_subprocess", _run)
    monkeypatch.setattr(subprocess_util, "run_subprocess_result", _result)


class TestObservedMainAdvanceClosesTrackers:
    """G1 (#10353) piece (a): the RC trackers close when ``main`` is OBSERVED to
    advance via a promotion the loop did NOT perform (a manual/operator merge),
    not only on the loop's own merge call. This is the miss that left the
    rc-promotion-stuck / rc_ci trackers open after a manual promotion this
    session."""

    RC_CI_ISSUE = 7001
    ESCALATION_ISSUE = 8002

    def _loop_with_open_trackers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, mark: int
    ) -> tuple[StagingPromotionLoop, MagicMock, StateTracker]:
        loop, prs = _make_loop(tmp_path, monkeypatch)
        state = StateTracker(state_file=tmp_path / "s.json")
        # Both rolling trackers OPEN + a live failure streak.
        state.set_rollup_issue(
            "staging_promotion:rc_ci",
            issue_number=self.RC_CI_ISSUE,
            content_hash="h",
        )
        state.set_rollup_issue(
            "staging_promotion:rc_promotion_stuck",
            issue_number=self.ESCALATION_ISSUE,
            content_hash="h",
        )
        state.increment_consecutive_rc_failures()
        state.increment_consecutive_rc_failures()
        if mark:
            state.set_last_observed_promotion_pr(mark)
        loop._state = state  # type: ignore[attr-defined]
        return loop, prs, state

    @pytest.mark.asyncio
    async def test_new_merged_rc_closes_both_trackers_and_resets_streak(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, state = self._loop_with_open_trackers(
            tmp_path, monkeypatch, mark=100
        )
        _install_gh_fake(
            monkeypatch,
            merged_prs=[{"number": 150, "headRefName": "rc/2026-07-23-1200"}],
        )
        closed = await loop._reconcile_observed_main_advance()
        assert closed == 2
        assert state.get_rollup_issue("staging_promotion:rc_ci") is None
        assert state.get_rollup_issue("staging_promotion:rc_promotion_stuck") is None
        assert state.get_consecutive_rc_failures() == 0
        assert state.get_last_observed_promotion_pr() == 150
        prs.close_issue.assert_any_await(self.RC_CI_ISSUE)
        prs.close_issue.assert_any_await(self.ESCALATION_ISSUE)

    @pytest.mark.asyncio
    async def test_bootstrap_records_mark_without_closing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # mark == 0 (never observed) → record baseline, DO NOT close: the open
        # trackers belong to the current red streak, not to a pre-existing merge.
        loop, prs, state = self._loop_with_open_trackers(tmp_path, monkeypatch, mark=0)
        _install_gh_fake(
            monkeypatch,
            merged_prs=[{"number": 150, "headRefName": "rc/2026-07-23-1200"}],
        )
        closed = await loop._reconcile_observed_main_advance()
        assert closed is None
        assert state.get_last_observed_promotion_pr() == 150
        assert state.get_rollup_issue("staging_promotion:rc_ci") is not None
        assert (
            state.get_rollup_issue("staging_promotion:rc_promotion_stuck") is not None
        )
        prs.close_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_new_advance_is_a_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, state = self._loop_with_open_trackers(
            tmp_path, monkeypatch, mark=150
        )
        _install_gh_fake(
            monkeypatch,
            merged_prs=[{"number": 150, "headRefName": "rc/2026-07-23-1200"}],
        )
        closed = await loop._reconcile_observed_main_advance()
        assert closed is None
        assert (
            state.get_rollup_issue("staging_promotion:rc_promotion_stuck") is not None
        )
        prs.close_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_rc_merges_are_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A merged main-base PR whose head is NOT an rc/* branch is not a
        # promotion — it must not count as a main advance for tracker purposes.
        loop, _prs, state = self._loop_with_open_trackers(
            tmp_path, monkeypatch, mark=100
        )
        _install_gh_fake(
            monkeypatch,
            merged_prs=[{"number": 900, "headRefName": "fix/some-branch"}],
        )
        closed = await loop._reconcile_observed_main_advance()
        assert closed is None
        assert (
            state.get_rollup_issue("staging_promotion:rc_promotion_stuck") is not None
        )

    @pytest.mark.asyncio
    async def test_noop_when_no_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs = _make_loop(tmp_path, monkeypatch)  # _state is None
        _install_gh_fake(
            monkeypatch,
            merged_prs=[{"number": 150, "headRefName": "rc/x"}],
        )
        assert await loop._reconcile_observed_main_advance() is None

    @pytest.mark.asyncio
    async def test_kill_switch_off_disables_the_sweep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # rc_observed_advance_close_enabled=False (the sandbox air-gap pin): the
        # sweep does NOT spawn `gh pr list` and never closes a tracker.
        monkeypatch.setenv("HYDRAFLOW_RC_OBSERVED_ADVANCE_CLOSE_ENABLED", "false")
        loop, prs, state = self._loop_with_open_trackers(
            tmp_path, monkeypatch, mark=100
        )
        _install_gh_fake(
            monkeypatch,
            merged_prs=[{"number": 150, "headRefName": "rc/2026-07-23-1200"}],
        )
        closed = await loop._reconcile_observed_main_advance()
        assert closed is None
        assert (
            state.get_rollup_issue("staging_promotion:rc_promotion_stuck") is not None
        )
        prs.close_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_do_work_manual_promotion_closes_trackers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end wiring: cadence not elapsed, no open PR, a manual promotion
        merged out of band → the tick closes the trackers via the reconciler."""
        loop, _prs, state = self._loop_with_open_trackers(
            tmp_path, monkeypatch, mark=100
        )
        loop._record_last_rc(datetime.now(UTC))  # cadence fresh → not elapsed
        _install_gh_fake(
            monkeypatch,
            merged_prs=[{"number": 151, "headRefName": "rc/2026-07-23-1300"}],
        )
        result = await loop._do_work()
        assert result.get("trackers_closed") == 2
        assert state.get_rollup_issue("staging_promotion:rc_promotion_stuck") is None
        assert state.get_last_observed_promotion_pr() == 151


class TestStagingCiGreenSensor:
    """G1 (#10353) piece (a): the NAMED-BLOCKING-GATE staging sensor used by
    auto-recut. Green iff every required-on-RC gate (read from the canonical
    ruleset) concluded ``success`` on staging HEAD — not merely the branch's
    latest run conclusion, which the advisory-on-staging / required-on-RC
    asymmetry can leave green while a required gate is red."""

    REQUIRED = ["Tests", "Sandbox (rc/* promotion PR full suite)"]

    @pytest.mark.asyncio
    async def test_all_required_gates_success_is_green(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs = _make_loop(tmp_path, monkeypatch)
        _write_canonical(tmp_path, self.REQUIRED)
        _install_gh_fake(
            monkeypatch,
            staging_gates={
                "Tests": "success",
                "Sandbox (rc/* promotion PR full suite)": "success",
            },
        )
        assert await loop._staging_ci_is_green() is True

    @pytest.mark.asyncio
    async def test_required_gate_red_hidden_behind_branch_green_is_not_green(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The exact dead-time trap: a required-on-RC gate is RED on staging while
        # other (advisory / unrelated) checks are green — the old branch-level
        # "latest run conclusion" read could report the branch green. The
        # named-gate sensor sees the specific required gate red → NOT green.
        loop, _prs = _make_loop(tmp_path, monkeypatch)
        _write_canonical(tmp_path, self.REQUIRED)
        _install_gh_fake(
            monkeypatch,
            staging_gates={
                "Tests": "success",
                "Sandbox (rc/* promotion PR full suite)": "failure",
                "Some Advisory Check": "success",
            },
        )
        assert await loop._staging_ci_is_green() is False

    @pytest.mark.asyncio
    async def test_missing_required_gate_is_not_green(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A required gate that never reported a check-run on staging HEAD gives
        # no positive confirmation → fail-closed (no recut).
        loop, _prs = _make_loop(tmp_path, monkeypatch)
        _write_canonical(tmp_path, self.REQUIRED)
        _install_gh_fake(monkeypatch, staging_gates={"Tests": "success"})
        assert await loop._staging_ci_is_green() is False

    @pytest.mark.asyncio
    async def test_undeterminable_gate_set_is_fail_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No canonical ruleset on disk → the required-gate set is undeterminable;
        # the sensor fails closed even though the check-runs it sees are green.
        loop, _prs = _make_loop(tmp_path, monkeypatch)  # no _write_canonical
        _install_gh_fake(monkeypatch, staging_gates={"Tests": "success"})
        assert await loop._staging_ci_is_green() is False

    @pytest.mark.asyncio
    async def test_check_runs_read_failure_is_fail_closed_no_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The non-raising check-runs read returns a non-zero rc (gh failure / the
        # loop-health air-gap) → no conclusions → every required gate absent →
        # sensor fail-closes (False) without raising.
        loop, _prs = _make_loop(tmp_path, monkeypatch)
        _write_canonical(tmp_path, self.REQUIRED)

        async def _result(*cmd: str, **_kwargs: object) -> SimpleResult:
            if cmd[:2] == ("gh", "api") and "/check-runs" in cmd[2]:
                return SimpleResult(stdout="", stderr="air-gapped", returncode=1)
            raise AssertionError(f"unexpected gh command: {cmd}")

        monkeypatch.setattr(subprocess_util, "run_subprocess_result", _result)
        assert await loop._staging_ci_is_green() is False

    @pytest.mark.asyncio
    async def test_rerun_latest_conclusion_wins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # When a gate reran on the same HEAD, the most recent run's conclusion
        # decides — a stale earlier failure must not mask a live success.
        loop, _prs = _make_loop(tmp_path, monkeypatch)
        _write_canonical(tmp_path, ["Tests"])

        async def _result(*cmd: str, **_kwargs: object) -> SimpleResult:
            if cmd[:2] == ("gh", "api") and "/check-runs" in cmd[2]:
                return SimpleResult(
                    stdout=json.dumps(
                        {
                            "check_runs": [
                                {
                                    "name": "Tests",
                                    "conclusion": "failure",
                                    "started_at": "2026-07-23T00:00:00Z",
                                },
                                {
                                    "name": "Tests",
                                    "conclusion": "success",
                                    "started_at": "2026-07-23T01:00:00Z",
                                },
                            ]
                        }
                    ),
                    returncode=0,
                )
            raise AssertionError(f"unexpected gh command: {cmd}")

        monkeypatch.setattr(subprocess_util, "run_subprocess_result", _result)
        assert await loop._staging_ci_is_green() is True


class TestAutoRecutDefaultOff:
    """G1 (#10353) piece (c): auto-recut is behind a default-OFF flag — it
    changes NO behaviour until ``HYDRAFLOW_RC_AUTO_RECUT_ENABLED`` is set."""

    ESCALATION_ISSUE = 8002

    def _stuck_loop(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        flag: bool,
        seed_tracker: bool = True,
    ) -> tuple[StagingPromotionLoop, MagicMock, StateTracker]:
        monkeypatch.setenv(
            "HYDRAFLOW_RC_AUTO_RECUT_ENABLED", "true" if flag else "false"
        )
        loop, prs = _make_loop(tmp_path, monkeypatch)
        # The named-gate sensor resolves required gates from the canonical
        # ruleset — one required gate ("Tests") is enough for these tests.
        _write_canonical(tmp_path, ["Tests"])
        state = StateTracker(state_file=tmp_path / "s.json")
        if seed_tracker:
            state.set_rollup_issue(
                "staging_promotion:rc_promotion_stuck",
                issue_number=self.ESCALATION_ISSUE,
                content_hash="h",
            )
        loop._state = state  # type: ignore[attr-defined]
        return loop, prs, state

    @pytest.mark.asyncio
    async def test_flag_off_never_recuts_even_when_stuck_and_green(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, _state = self._stuck_loop(tmp_path, monkeypatch, flag=False)
        _install_gh_fake(monkeypatch, staging_gates={"Tests": "success"})
        assert await loop._maybe_auto_recut() is None
        prs.create_rc_branch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_flag_on_stuck_and_green_recuts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, _state = self._stuck_loop(tmp_path, monkeypatch, flag=True)
        _install_gh_fake(monkeypatch, staging_gates={"Tests": "success"})
        result = await loop._maybe_auto_recut()
        assert result is not None
        assert result.get("auto_recut") is True
        assert result["status"] == "opened"
        prs.create_rc_branch.assert_awaited_once()
        prs.create_promotion_pr.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_flag_on_but_staging_red_does_not_recut(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, _state = self._stuck_loop(tmp_path, monkeypatch, flag=True)
        _install_gh_fake(monkeypatch, staging_gates={"Tests": "failure"})
        assert await loop._maybe_auto_recut() is None
        prs.create_rc_branch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_flag_on_but_no_open_escalation_does_not_recut(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, _state = self._stuck_loop(
            tmp_path, monkeypatch, flag=True, seed_tracker=False
        )
        _install_gh_fake(monkeypatch, staging_gates={"Tests": "success"})
        assert await loop._maybe_auto_recut() is None
        prs.create_rc_branch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_do_work_flag_off_reports_cadence_not_elapsed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, _state = self._stuck_loop(tmp_path, monkeypatch, flag=False)
        loop._record_last_rc(datetime.now(UTC))  # cadence fresh → not elapsed
        _install_gh_fake(monkeypatch, merged_prs=[], staging_gates={"Tests": "success"})
        result = await loop._do_work()
        assert result["status"] == "cadence_not_elapsed"
        prs.create_rc_branch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_do_work_flag_on_recuts_ahead_of_cadence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, _state = self._stuck_loop(tmp_path, monkeypatch, flag=True)
        loop._record_last_rc(datetime.now(UTC))  # cadence NOT elapsed
        _install_gh_fake(monkeypatch, merged_prs=[], staging_gates={"Tests": "success"})
        result = await loop._do_work()
        assert result.get("auto_recut") is True
        assert result["status"] == "opened"
        prs.create_rc_branch.assert_awaited_once()


class TestPromotionHealthSignal:
    """G1 (#10353) piece (b): the promotion error-signal — `main..staging` gap +
    days_since_last_successful_promotion + consecutive_rc_failures — surfaces as
    observable state in the loop's BACKGROUND_WORKER_STATUS details, so promotion
    health is measurable, not merely implied."""

    def _stateful_loop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[StagingPromotionLoop, MagicMock, StateTracker]:
        loop, prs = _make_loop(tmp_path, monkeypatch)
        loop._record_last_rc(datetime.now(UTC))  # cadence fresh → not elapsed
        state = StateTracker(state_file=tmp_path / "s.json")
        loop._state = state  # type: ignore[attr-defined]
        return loop, prs, state

    @pytest.mark.asyncio
    async def test_all_three_signals_surface_in_do_work(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, state = self._stateful_loop(tmp_path, monkeypatch)
        state.increment_consecutive_rc_failures()
        state.increment_consecutive_rc_failures()
        state.set_last_successful_promotion_at(
            (datetime.now(UTC) - timedelta(days=2)).isoformat()
        )
        _install_gh_fake(monkeypatch, merged_prs=[], gap=5)

        result = await loop._do_work()

        health = result["promotion_health"]
        assert health["main_staging_gap"] == 5
        assert health["consecutive_rc_failures"] == 2
        assert 1.9 < health["days_since_last_successful_promotion"] < 2.1

    @pytest.mark.asyncio
    async def test_days_since_is_none_when_never_promoted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, _state = self._stateful_loop(tmp_path, monkeypatch)
        _install_gh_fake(monkeypatch, merged_prs=[], gap=0)
        result = await loop._do_work()
        health = result["promotion_health"]
        assert health["days_since_last_successful_promotion"] is None
        assert health["main_staging_gap"] == 0

    @pytest.mark.asyncio
    async def test_gap_none_and_no_spawn_when_health_flag_off(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The sandbox air-gap pin: flag OFF → the gap's `gh api compare` spawn is
        # never reached; the two state-only signals still surface.
        monkeypatch.setenv("HYDRAFLOW_RC_PROMOTION_HEALTH_ENABLED", "false")
        loop, _prs, state = self._stateful_loop(tmp_path, monkeypatch)
        state.increment_consecutive_rc_failures()

        async def _run(*cmd: str, **_kwargs: object) -> str:
            if cmd[:3] == ("gh", "pr", "list"):
                return "[]"
            raise AssertionError(f"unexpected run_subprocess command: {cmd}")

        async def _result(*cmd: str, **_kwargs: object) -> SimpleResult:
            if cmd[:2] == ("gh", "api") and "/compare/" in cmd[2]:
                raise AssertionError("compare must NOT be read when health flag off")
            raise AssertionError(f"unexpected run_subprocess_result command: {cmd}")

        monkeypatch.setattr(subprocess_util, "run_subprocess", _run)
        monkeypatch.setattr(subprocess_util, "run_subprocess_result", _result)
        result = await loop._do_work()
        health = result["promotion_health"]
        assert health["main_staging_gap"] is None
        assert health["consecutive_rc_failures"] == 1

    @pytest.mark.asyncio
    async def test_no_health_key_when_state_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs = _make_loop(tmp_path, monkeypatch)  # _state is None
        loop._record_last_rc(datetime.now(UTC))
        result = await loop._do_work()
        assert "promotion_health" not in result

    @pytest.mark.asyncio
    async def test_gap_read_failure_degrades_to_none_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A telemetry read must NEVER take down the tick. The non-raising
        # run_subprocess_result returns a non-zero rc (e.g. the MockWorld
        # loop-health harness's air-gap, or a gh 404) → the gap degrades to
        # None and `_do_work` completes normally.
        loop, _prs, _state = self._stateful_loop(tmp_path, monkeypatch)

        async def _run(*cmd: str, **_kwargs: object) -> str:
            if cmd[:3] == ("gh", "pr", "list"):
                return "[]"
            raise AssertionError(f"unexpected run_subprocess command: {cmd}")

        async def _result(*cmd: str, **_kwargs: object) -> SimpleResult:
            if cmd[:2] == ("gh", "api") and "/compare/" in cmd[2]:
                return SimpleResult(stdout="", stderr="air-gapped", returncode=1)
            raise AssertionError(f"unexpected run_subprocess_result command: {cmd}")

        monkeypatch.setattr(subprocess_util, "run_subprocess", _run)
        monkeypatch.setattr(subprocess_util, "run_subprocess_result", _result)
        result = await loop._do_work()  # must not raise
        assert result["promotion_health"]["main_staging_gap"] is None

    @pytest.mark.asyncio
    async def test_last_successful_promotion_recorded_on_promoted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(number=77),
            ci_result=(True, "ok"),
            merge_result=True,
        )
        prs.get_pr_head_sha = AsyncMock(return_value="abc123")
        state = StateTracker(state_file=tmp_path / "s.json")
        loop._state = state  # type: ignore[attr-defined]

        result = await loop._do_work()

        assert result["status"] == "promoted"
        assert state.get_last_successful_promotion_at() != ""

    @pytest.mark.asyncio
    async def test_last_successful_promotion_recorded_on_observed_advance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs = _make_loop(tmp_path, monkeypatch)
        state = StateTracker(state_file=tmp_path / "s.json")
        state.set_last_observed_promotion_pr(100)  # baseline already bootstrapped
        loop._state = state  # type: ignore[attr-defined]
        _install_gh_fake(
            monkeypatch,
            merged_prs=[{"number": 150, "headRefName": "rc/2026-07-23-1200"}],
        )
        closed = await loop._reconcile_observed_main_advance()
        assert closed == 0  # no open trackers, but main advanced
        assert state.get_last_successful_promotion_at() != ""
