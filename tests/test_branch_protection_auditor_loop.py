"""Unit tests for BranchProtectionAuditorLoop (ADR-0082)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from branch_protection_audit import AuditReport
from branch_protection_auditor_loop import BranchProtectionAuditorLoop
from dedup_store import DedupStore
from tests.helpers import make_bg_loop_deps

_CLEAN = AuditReport(repo="o/r", drifts=[])
_DRIFT = AuditReport(
    repo="o/r", drifts=["[main protect] DRIFT: canonical and live differ."]
)


def _build(
    tmp_path: Path,
    *,
    report: AuditReport,
    enabled: bool = True,
    loop_enabled: bool = True,
    **overrides,
):
    deps = make_bg_loop_deps(tmp_path, enabled=enabled, **overrides)
    # HydraFlowConfig is frozen; model_copy to flip the config kill-switch.
    config = deps.config.model_copy(
        update={"branch_protection_auditor_loop_enabled": loop_enabled}
    )
    pr = MagicMock()
    pr.create_issue = AsyncMock(return_value=4242)
    dedup = DedupStore("bpa", tmp_path / "bpa.json")
    auditor = AsyncMock(return_value=report)
    loop = BranchProtectionAuditorLoop(
        config=config,
        pr_manager=pr,
        dedup=dedup,
        deps=deps.loop_deps,
        auditor=auditor,
    )
    return loop, pr, dedup, auditor


async def test_clean_files_no_issue(tmp_path: Path) -> None:
    loop, pr, _dedup, _auditor = _build(tmp_path, report=_CLEAN)
    assert await loop._do_work() == {"status": "clean"}
    pr.create_issue.assert_not_awaited()


async def test_drift_files_one_issue(tmp_path: Path) -> None:
    loop, pr, dedup, _auditor = _build(tmp_path, report=_DRIFT)
    result = await loop._do_work()
    assert result == {"status": "drift", "issue_created": 4242}
    pr.create_issue.assert_awaited_once()
    title, body = pr.create_issue.await_args.args[:2]
    assert "branch-protection" in title
    assert "make gen-gates" in body
    assert pr.create_issue.await_args.kwargs["labels"] == [
        "hydraflow-find",
        "hydraflow-branch-protection-drift",
    ]
    assert len(dedup.get()) == 1


async def test_same_drift_is_deduped(tmp_path: Path) -> None:
    loop, pr, _dedup, _auditor = _build(tmp_path, report=_DRIFT)
    await loop._do_work()
    pr.create_issue.reset_mock()
    assert await loop._do_work() == {"status": "drift", "deduped": True}
    pr.create_issue.assert_not_awaited()


async def test_disabled_kill_switch_skips_audit(tmp_path: Path) -> None:
    loop, _pr, _dedup, auditor = _build(tmp_path, report=_DRIFT, enabled=False)
    assert await loop._do_work() == {"status": "disabled"}
    auditor.assert_not_awaited()


async def test_config_kill_switch_skips_audit(tmp_path: Path) -> None:
    loop, _pr, _dedup, auditor = _build(tmp_path, report=_DRIFT, loop_enabled=False)
    assert await loop._do_work() == {"status": "config_disabled"}
    auditor.assert_not_awaited()


async def test_dry_run_skips_audit(tmp_path: Path) -> None:
    loop, _pr, _dedup, auditor = _build(tmp_path, report=_DRIFT, dry_run=True)
    assert await loop._do_work() is None
    auditor.assert_not_awaited()


async def test_auditor_failure_is_caught(tmp_path: Path) -> None:
    loop, pr, _dedup, _auditor = _build(tmp_path, report=_CLEAN)
    loop._auditor = AsyncMock(side_effect=Exception("transient gh failure"))
    assert await loop._do_work() == {"error": True}
    pr.create_issue.assert_not_awaited()


async def test_default_interval_from_config(tmp_path: Path) -> None:
    loop, _pr, _dedup, _auditor = _build(tmp_path, report=_CLEAN)
    assert (
        loop._get_default_interval() == loop._config.branch_protection_auditor_interval
    )
