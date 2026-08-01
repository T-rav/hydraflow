"""Unit tests for BranchProtectionAuditorLoop (ADR-0082)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from branch_protection_audit import AuditReport
from branch_protection_auditor_loop import BranchProtectionAuditorLoop, _issue_body
from dedup_store import DedupStore
from tests.helpers import make_bg_loop_deps

_CLEAN = AuditReport(repo="o/r", drifts=[])
_DRIFT = AuditReport(
    repo="o/r", drifts=["[main protect] DRIFT: canonical and live differ."]
)
# A drift that INCLUDES an undeclared live context (the #10894 hazard): live
# requires `CI Gate` via the legacy layer, but the contract never declared it.
_UNDECLARED_DRIFT = AuditReport(
    repo="o/r",
    drifts=[
        "[staging] undeclared legacy branch-protection context(s) required "
        "live but not in the declarative contract: CI Gate"
    ],
)


def test_issue_body_for_normal_drift_prescribes_reapply() -> None:
    body = _issue_body(_DRIFT)
    # The plain reconcile path is correct when the contract is a superset of live.
    assert "python scripts/setup_branch_protection.py --apply" in body


def test_issue_body_for_undeclared_contexts_does_not_lead_with_bare_apply() -> None:
    # #10894: when live requires a context the contract never declared, running
    # `--apply` PUTs the canonical payload verbatim and silently de-requires it
    # (e.g. the CI Gate umbrella, regressing #10672). The body must prescribe
    # DECLARING the missing gate first, and warn about the de-require.
    body = _issue_body(_UNDECLARED_DRIFT)
    assert "gates.toml" in body
    assert "ADDING-A-GATE" in body
    # It must name the endangered context and warn that --apply would remove it.
    assert "CI Gate" in body
    lowered = body.lower()
    assert "de-require" in lowered or "silently remove" in lowered
    # It must NOT present the bare `--apply` block as the primary remediation.
    assert (
        "make gen-gates\npython scripts/setup_branch_protection.py --apply" not in body
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
    pr.find_existing_issue = AsyncMock(return_value=0)
    pr.close_issue = AsyncMock()
    pr.post_comment = AsyncMock()
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


async def test_undeclared_context_drift_files_declare_first_body(
    tmp_path: Path,
) -> None:
    # #10894: the declare-first guidance must reach the actually-filed issue, not
    # just _issue_body in isolation.
    loop, pr, _dedup, _auditor = _build(tmp_path, report=_UNDECLARED_DRIFT)
    result = await loop._do_work()
    assert result == {"status": "drift", "issue_created": 4242}
    _title, body = pr.create_issue.await_args.args[:2]
    assert "ADDING-A-GATE" in body
    assert (
        "make gen-gates\npython scripts/setup_branch_protection.py --apply" not in body
    )


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


async def test_clean_closes_open_drift_issue_and_clears_dedup(tmp_path: Path) -> None:
    """#9359: when drift resolves, close the open drift issue and clear the dedup
    so a future drift re-files."""
    loop, pr, dedup, _auditor = _build(tmp_path, report=_DRIFT)
    # First tick files + dedups.
    await loop._do_work()
    assert len(dedup.get()) == 1
    # Now the ruleset is back in sync → clean report.
    loop._auditor = AsyncMock(return_value=_CLEAN)  # type: ignore[attr-defined]
    pr.find_existing_issue = AsyncMock(return_value=4242)
    result = await loop._do_work()
    assert result == {"status": "clean"}
    pr.close_issue.assert_awaited_once_with(4242)
    assert dedup.get() == set()
