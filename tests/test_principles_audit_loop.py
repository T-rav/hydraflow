"""Tests for PrinciplesAuditLoop."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig, ManagedRepo
from events import EventBus
from principles_audit_loop import PrinciplesAuditLoop


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    cfg.managed_repos = []
    state = MagicMock()
    state.blocked_slugs.return_value = set()
    state.get_onboarding_status.return_value = None
    state.get_last_green_audit.return_value = {}
    state.get_drift_attempts.return_value = 0
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)
    return cfg, state, pr_manager


def test_skeleton_worker_name_and_interval(loop_env):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        deps=_deps(stop),
    )
    assert loop._worker_name == "principles_audit"  # type: ignore[attr-defined]
    assert loop._get_default_interval() == 604800  # spec §4.4


async def test_audit_hydraflow_self_saves_snapshot(loop_env, tmp_path, monkeypatch):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))

    fake_findings = [
        {
            "check_id": "P1.1",
            "status": "PASS",
            "severity": "STRUCTURAL",
            "principle": "P1",
            "source": "docs/adr",
            "what": "doc exists",
            "remediation": "write docs",
            "message": "",
        },
        {
            "check_id": "P2.4",
            "status": "PASS",
            "severity": "BEHAVIORAL",
            "principle": "P2",
            "source": "Makefile",
            "what": "target runs",
            "remediation": "fix target",
            "message": "",
        },
    ]

    async def fake_run_audit(slug, repo_root):
        return {"summary": {}, "findings": fake_findings}

    monkeypatch.setattr(loop, "_run_audit", fake_run_audit)

    snapshot = await loop._audit_hydraflow_self()
    assert snapshot == {"P1.1": "PASS", "P2.4": "PASS"}
    snap_dir = cfg.data_root / "hydraflow-self" / "audit"
    saved = list(snap_dir.glob("*.json"))
    assert len(saved) == 1


async def test_audit_managed_repo_clones_or_fetches(loop_env, tmp_path, monkeypatch):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))
    mr = ManagedRepo(slug="acme/widget")
    commands: list[list[str]] = []

    async def fake_run_git(*args, cwd=None):
        commands.append(list(args))
        return 0, ""

    async def fake_run_audit(slug, repo_root):
        return {
            "findings": [
                {
                    "check_id": "P1.1",
                    "status": "PASS",
                    "severity": "STRUCTURAL",
                    "principle": "P1",
                    "source": "",
                    "what": "",
                    "remediation": "",
                    "message": "",
                }
            ]
        }

    monkeypatch.setattr(loop, "_run_git", fake_run_git)
    monkeypatch.setattr(loop, "_run_audit", fake_run_audit)
    snap = await loop._audit_managed_repo(mr)
    assert snap == {"P1.1": "PASS"}
    # first run → clone
    assert any("clone" in c for c in commands)

    # second call with dir present → fetch
    (cfg.data_root / "acme/widget" / "audit-checkout").mkdir(
        parents=True, exist_ok=True
    )
    commands.clear()
    await loop._audit_managed_repo(mr)
    assert any("fetch" in c for c in commands)


def test_diff_regressions_identifies_pass_to_fail(loop_env):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))
    last = {"P1.1": "PASS", "P2.4": "PASS", "P8.2": "WARN"}
    current = {"P1.1": "FAIL", "P2.4": "PASS", "P8.2": "FAIL"}
    regressions = loop._diff_regressions(last, current)
    # Only PASS→FAIL is a regression; WARN→FAIL is not (spec §4.4 "PASS to FAIL")
    assert set(regressions) == {"P1.1"}


def test_diff_regressions_no_reference_is_noop(loop_env):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))
    # Empty last-green means "we don't know what green is yet" — no regressions.
    assert loop._diff_regressions({}, {"P1.1": "FAIL"}) == []


async def test_file_drift_issue_creates_hydraflow_find(loop_env):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))
    finding = {
        "check_id": "P1.1",
        "severity": "STRUCTURAL",
        "principle": "P1",
        "source": "docs/adr/0001",
        "what": "doc exists",
        "remediation": "write docs",
        "message": "missing file",
    }
    issue_num = await loop._file_drift_issue("acme/widget", finding, "PASS")
    assert issue_num == 42
    pr.create_issue.assert_awaited_once()
    call_args = pr.create_issue.await_args
    title = call_args.args[0] if call_args.args else call_args.kwargs["title"]
    assert "acme/widget" in title and "P1.1" in title


async def test_structural_escalates_after_three_attempts(loop_env):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))
    state.increment_drift_attempts.side_effect = [1, 2, 3]
    # Three consecutive failures → third call fires escalation
    escalated_last = None
    for _ in range(3):
        escalated = await loop._maybe_escalate("acme/widget", "P1.1", "STRUCTURAL")
        escalated_last = escalated
    assert escalated_last is True


async def test_cultural_escalates_after_one_attempt(loop_env):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))
    state.increment_drift_attempts.return_value = 1
    escalated = await loop._maybe_escalate("acme/widget", "P10.2", "CULTURAL")
    assert escalated is True


async def test_onboarding_pending_triggers_initial_audit(loop_env, monkeypatch):
    cfg, state, pr = loop_env
    cfg.managed_repos = [ManagedRepo(slug="acme/widget")]
    state.get_onboarding_status.return_value = None  # unseen → pending
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))

    async def fake_audit(mr):
        # P1.1 FAIL (structural P1–P5) — must block
        return {"P1.1": "FAIL", "P6.1": "PASS"}

    async def fake_report(mr):
        return {
            "findings": [
                {
                    "check_id": "P1.1",
                    "status": "FAIL",
                    "severity": "STRUCTURAL",
                    "principle": "P1",
                    "source": "",
                    "what": "",
                    "remediation": "",
                    "message": "",
                },
                {
                    "check_id": "P6.1",
                    "status": "PASS",
                    "severity": "BEHAVIORAL",
                    "principle": "P6",
                    "source": "",
                    "what": "",
                    "remediation": "",
                    "message": "",
                },
            ]
        }

    monkeypatch.setattr(loop, "_audit_managed_repo", fake_audit)
    monkeypatch.setattr(loop, "_fetch_last_report", fake_report)

    await loop._reconcile_onboarding()

    state.set_onboarding_status.assert_called_with("acme/widget", "blocked")
    pr.create_issue.assert_awaited()  # onboarding-blocked issue filed


def test_p1_p5_fails_filter():
    # Module-level helper check
    from principles_audit_loop import PrinciplesAuditLoop as PAL

    findings = [
        {"check_id": "P1.1", "status": "FAIL", "principle": "P1"},
        {"check_id": "P5.2", "status": "FAIL", "principle": "P5"},
        {"check_id": "P6.1", "status": "FAIL", "principle": "P6"},
        {"check_id": "P2.1", "status": "PASS", "principle": "P2"},
    ]
    assert PAL._p1_p5_fails(findings) == ["P1.1", "P5.2"]


async def test_blocked_flips_to_ready_on_green(loop_env, monkeypatch):
    cfg, state, pr = loop_env
    cfg.managed_repos = [ManagedRepo(slug="acme/widget")]
    state.get_onboarding_status.return_value = "blocked"
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))

    async def fake_audit(mr):
        return {"P1.1": "PASS", "P5.1": "PASS"}

    async def fake_report(mr):
        return {
            "findings": [
                {
                    "check_id": "P1.1",
                    "status": "PASS",
                    "severity": "STRUCTURAL",
                    "principle": "P1",
                    "source": "",
                    "what": "",
                    "remediation": "",
                    "message": "",
                },
                {
                    "check_id": "P5.1",
                    "status": "PASS",
                    "severity": "STRUCTURAL",
                    "principle": "P5",
                    "source": "",
                    "what": "",
                    "remediation": "",
                    "message": "",
                },
            ]
        }

    monkeypatch.setattr(loop, "_audit_managed_repo", fake_audit)
    monkeypatch.setattr(loop, "_fetch_last_report", fake_report)

    flipped = await loop._retry_blocked()

    assert flipped == 1
    state.set_onboarding_status.assert_called_with("acme/widget", "ready")
    state.set_last_green_audit.assert_called_with(
        "acme/widget", {"P1.1": "PASS", "P5.1": "PASS"}
    )


async def test_blocked_stays_blocked_when_p1_p5_still_failing(loop_env, monkeypatch):
    cfg, state, pr = loop_env
    cfg.managed_repos = [ManagedRepo(slug="acme/widget")]
    state.get_onboarding_status.return_value = "blocked"
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))

    async def fake_audit(mr):
        return {"P1.1": "FAIL"}

    async def fake_report(mr):
        return {
            "findings": [
                {
                    "check_id": "P1.1",
                    "status": "FAIL",
                    "severity": "STRUCTURAL",
                    "principle": "P1",
                    "source": "",
                    "what": "",
                    "remediation": "",
                    "message": "",
                },
            ]
        }

    monkeypatch.setattr(loop, "_audit_managed_repo", fake_audit)
    monkeypatch.setattr(loop, "_fetch_last_report", fake_report)

    flipped = await loop._retry_blocked()

    assert flipped == 0
    # No ready flip; no last-green write.
    for call in state.set_onboarding_status.call_args_list:
        assert call.args != ("acme/widget", "ready")
    state.set_last_green_audit.assert_not_called()


async def test_do_work_runs_end_to_end(loop_env, monkeypatch):
    cfg, state, pr = loop_env
    cfg.managed_repos = []
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))

    self_findings = [
        {
            "check_id": "P1.1",
            "status": "PASS",
            "severity": "STRUCTURAL",
            "principle": "P1",
            "source": "",
            "what": "",
            "remediation": "",
            "message": "",
        },
    ]

    async def fake_run_audit(slug, root):
        return {"summary": {}, "findings": self_findings}

    monkeypatch.setattr(loop, "_run_audit", fake_run_audit)
    state.get_last_green_audit.return_value = {}

    stats = await loop._do_work()

    assert stats["audited"] >= 1
    assert stats["onboarded"] == 0
    assert stats["ready_flips"] == 0
    # All green on first run — last-green must be refreshed.
    state.set_last_green_audit.assert_called_with("hydraflow-self", {"P1.1": "PASS"})


async def test_do_work_managed_repo_regression_files_drift(loop_env, monkeypatch):
    cfg, state, pr = loop_env
    cfg.managed_repos = [ManagedRepo(slug="acme/widget")]
    state.get_onboarding_status.return_value = "ready"
    state.get_last_green_audit.side_effect = lambda slug: (
        {"P3.1": "PASS"} if slug == "acme/widget" else {}
    )
    state.increment_drift_attempts.return_value = 1
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))

    self_findings = [
        {
            "check_id": "P1.1",
            "status": "PASS",
            "severity": "STRUCTURAL",
            "principle": "P1",
            "source": "",
            "what": "",
            "remediation": "",
            "message": "",
        },
    ]

    async def fake_run_audit(slug, root):
        return {"summary": {}, "findings": self_findings}

    async def fake_audit_managed(mr):
        return {"P3.1": "FAIL"}

    async def fake_fetch_last(mr):
        return {
            "findings": [
                {
                    "check_id": "P3.1",
                    "status": "FAIL",
                    "severity": "STRUCTURAL",
                    "principle": "P3",
                    "source": "",
                    "what": "",
                    "remediation": "",
                    "message": "",
                },
            ]
        }

    monkeypatch.setattr(loop, "_run_audit", fake_run_audit)
    monkeypatch.setattr(loop, "_audit_managed_repo", fake_audit_managed)
    monkeypatch.setattr(loop, "_fetch_last_report", fake_fetch_last)

    stats = await loop._do_work()

    assert stats["audited"] == 2  # self + acme/widget
    assert stats["regressions_filed"] == 1
    pr.create_issue.assert_awaited()
