"""Tests for the persistent-error self-repair actuator (#10140).

Follow-up to #9854's read-only per-loop health harness
(``tests/scenarios/test_loop_health.py``) — this is the ACTUATOR half.
``_check_persistent_worker_errors`` watches ``state.get_worker_heartbeats()``
for a registry loop whose heartbeat reports ``error`` for
``_ERROR_STREAK_THRESHOLD`` consecutive health_monitor ticks and either:

* auto-repairs a KNOWN pattern (v1: PrinciplesAuditLoop's ``managed_repos``
  404-repo prune — ``_repair_principles_audit_404_repo`` / ``_repo_probe``),
  or
* files ONE deduped ``hydraflow-find`` + ``loop-persistent-error`` issue via
  ``RollupIssueManager``, naming the loop.

Mirrors the structure of ``test_health_monitor_worker_stall.py`` (the sibling
silent-heartbeat dead-man-switch this complements).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import health_monitor_loop
from base_background_loop import LoopDeps
from config import HydraFlowConfig, ManagedRepo
from events import EventBus
from execution import SimpleResult
from health_monitor_loop import _ERROR_STREAK_THRESHOLD, HealthMonitorLoop
from state import StateTracker
from subprocess_util import CreditExhaustedError

pytestmark = pytest.mark.asyncio


def _deps() -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


def _hb(status: str) -> dict:
    return {"status": status, "last_run": "2026-01-01T00:00:00+00:00", "details": {}}


def _result(returncode: int, stdout: str = "", stderr: str = "") -> SimpleResult:
    return SimpleResult(stdout=stdout, stderr=stderr, returncode=returncode)


# ---------------------------------------------------------------------------
# Generic actuator logic (streak / dedup / kill-switch / issue filing) —
# `__new__`-bypassed with NO known repairs wired, so these exercise
# `_check_persistent_worker_errors` in isolation from the concrete
# `principles_audit` repair pattern below.
# ---------------------------------------------------------------------------


@pytest.fixture
def hm_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = StateTracker(state_file=tmp_path / "state.json")
    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=501)
    prs.update_issue_body = AsyncMock()
    prs.post_comment = AsyncMock()
    prs.close_issue = AsyncMock()
    hm = HealthMonitorLoop.__new__(HealthMonitorLoop)
    hm._config = cfg
    hm._state = state
    hm._prs = prs
    hm._bus = AsyncMock()
    hm._error_streaks = {}
    hm._known_repairs = {}
    return hm, state, prs


async def test_healthy_loop_no_action(hm_env) -> None:
    hm, state, prs = hm_env
    state.set_worker_heartbeat("flake_tracker", _hb("ok"))
    await hm._check_persistent_worker_errors()
    prs.create_issue.assert_not_awaited()
    assert hm._error_streaks.get("flake_tracker", 0) == 0


async def test_below_threshold_no_action(hm_env) -> None:
    hm, state, prs = hm_env
    state.set_worker_heartbeat("flake_tracker", _hb("error"))
    for _ in range(_ERROR_STREAK_THRESHOLD - 1):
        await hm._check_persistent_worker_errors()
    prs.create_issue.assert_not_awaited()
    assert hm._error_streaks["flake_tracker"] == _ERROR_STREAK_THRESHOLD - 1


async def test_threshold_crossed_files_one_issue(hm_env) -> None:
    hm, state, prs = hm_env
    state.set_worker_heartbeat("flake_tracker", _hb("error"))
    for _ in range(_ERROR_STREAK_THRESHOLD):
        await hm._check_persistent_worker_errors()
    prs.create_issue.assert_awaited_once()
    title, body, labels = prs.create_issue.await_args.args
    assert "flake_tracker" in title
    assert "loop-persistent-error" in title
    assert "hydraflow-find" in labels
    assert "loop-persistent-error" in labels
    assert "none registered for this loop" in body


async def test_dedup_no_refile_on_repeated_ticks(hm_env) -> None:
    hm, state, prs = hm_env
    state.set_worker_heartbeat("flake_tracker", _hb("error"))
    for _ in range(_ERROR_STREAK_THRESHOLD + 3):
        await hm._check_persistent_worker_errors()
    assert prs.create_issue.await_count == 1


async def test_recovery_closes_issue_and_resets_streak(hm_env) -> None:
    hm, state, prs = hm_env
    state.set_worker_heartbeat("flake_tracker", _hb("error"))
    for _ in range(_ERROR_STREAK_THRESHOLD):
        await hm._check_persistent_worker_errors()
    assert prs.create_issue.await_count == 1

    state.set_worker_heartbeat("flake_tracker", _hb("ok"))
    await hm._check_persistent_worker_errors()
    prs.close_issue.assert_awaited_once_with(501)
    assert hm._error_streaks["flake_tracker"] == 0

    # Fresh streak re-files from scratch.
    state.set_worker_heartbeat("flake_tracker", _hb("error"))
    for _ in range(_ERROR_STREAK_THRESHOLD):
        await hm._check_persistent_worker_errors()
    assert prs.create_issue.await_count == 2


async def test_excluded_workers_never_actuated(hm_env) -> None:
    hm, state, prs = hm_env
    for name in ("trust_fleet_sanity", "health_monitor"):
        state.set_worker_heartbeat(name, _hb("error"))
    for _ in range(_ERROR_STREAK_THRESHOLD + 2):
        await hm._check_persistent_worker_errors()
    prs.create_issue.assert_not_awaited()


async def test_kill_switch_disables_actuator(hm_env) -> None:
    hm, state, prs = hm_env
    object.__setattr__(hm._config, "self_repair_actuator_enabled", False)
    state.set_worker_heartbeat("flake_tracker", _hb("error"))
    for _ in range(_ERROR_STREAK_THRESHOLD + 2):
        await hm._check_persistent_worker_errors()
    prs.create_issue.assert_not_awaited()
    assert hm._error_streaks == {}


async def test_missing_state_is_silent_noop(hm_env) -> None:
    hm, _state, prs = hm_env
    hm._state = None
    await hm._check_persistent_worker_errors()
    prs.create_issue.assert_not_awaited()


async def test_missing_prs_is_silent_noop(hm_env) -> None:
    hm, state, _prs = hm_env
    hm._prs = None
    state.set_worker_heartbeat("flake_tracker", _hb("error"))
    await hm._check_persistent_worker_errors()  # must not raise


async def test_known_repair_success_resets_streak_no_issue(hm_env) -> None:
    hm, state, prs = hm_env
    repair = AsyncMock(return_value="bad/repo")
    hm._known_repairs = {"principles_audit": repair}
    state.set_worker_heartbeat("principles_audit", _hb("error"))
    for _ in range(_ERROR_STREAK_THRESHOLD):
        await hm._check_persistent_worker_errors()
    repair.assert_awaited_once()
    prs.create_issue.assert_not_awaited()
    assert hm._error_streaks["principles_audit"] == 0


async def test_known_repair_none_falls_through_to_issue(hm_env) -> None:
    hm, state, prs = hm_env
    repair = AsyncMock(return_value=None)
    hm._known_repairs = {"principles_audit": repair}
    state.set_worker_heartbeat("principles_audit", _hb("error"))
    for _ in range(_ERROR_STREAK_THRESHOLD):
        await hm._check_persistent_worker_errors()
    repair.assert_awaited_once()
    prs.create_issue.assert_awaited_once()
    _title, body, _labels = prs.create_issue.await_args.args
    assert "attempted — no matching condition found" in body


async def test_known_repair_attempted_only_once_per_streak(hm_env) -> None:
    hm, state, prs = hm_env
    repair = AsyncMock(return_value=None)
    hm._known_repairs = {"principles_audit": repair}
    state.set_worker_heartbeat("principles_audit", _hb("error"))
    for _ in range(_ERROR_STREAK_THRESHOLD + 3):
        await hm._check_persistent_worker_errors()
    assert repair.await_count == 1
    assert prs.create_issue.await_count == 1


# ---------------------------------------------------------------------------
# Concrete known-repair pattern: PrinciplesAuditLoop's `managed_repos`
# 404-repo prune. Built via the REAL constructor so `_known_repairs` wiring
# comes from `__init__` itself, not hand-assembled by the test.
# ---------------------------------------------------------------------------


def _real_loop(
    tmp_path: Path, *, managed_repos: list[ManagedRepo]
) -> tuple[HealthMonitorLoop, AsyncMock, StateTracker, HydraFlowConfig]:
    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        managed_repos=managed_repos,
    )
    prs = AsyncMock()
    prs.create_issue = AsyncMock(return_value=777)
    state = StateTracker(state_file=tmp_path / "state2.json")
    loop = HealthMonitorLoop(config=cfg, deps=_deps(), prs=prs, state=state)
    return loop, prs, state, cfg


async def test_repo_probe_confirmed_404(tmp_path: Path, monkeypatch) -> None:
    loop, *_ = _real_loop(tmp_path, managed_repos=[])
    mock = AsyncMock(
        return_value=_result(
            128,
            stderr="fatal: repository 'https://github.com/a/b.git/' not found",
        )
    )
    monkeypatch.setattr(health_monitor_loop, "run_subprocess_result", mock)
    assert await loop._repo_probe("a/b") is False


async def test_repo_probe_reachable(tmp_path: Path, monkeypatch) -> None:
    loop, *_ = _real_loop(tmp_path, managed_repos=[])
    mock = AsyncMock(return_value=_result(0, stdout="abc123\tHEAD\n"))
    monkeypatch.setattr(health_monitor_loop, "run_subprocess_result", mock)
    assert await loop._repo_probe("a/b") is True


async def test_repo_probe_ambiguous_failure_fails_open(
    tmp_path: Path, monkeypatch
) -> None:
    loop, *_ = _real_loop(tmp_path, managed_repos=[])
    mock = AsyncMock(
        return_value=_result(
            128, stderr="fatal: unable to access ...: Could not resolve host"
        )
    )
    monkeypatch.setattr(health_monitor_loop, "run_subprocess_result", mock)
    assert await loop._repo_probe("a/b") is None


async def test_repo_probe_credit_exhausted_reraises(
    tmp_path: Path, monkeypatch
) -> None:
    loop, *_ = _real_loop(tmp_path, managed_repos=[])
    mock = AsyncMock(side_effect=CreditExhaustedError("out of credit"))
    monkeypatch.setattr(health_monitor_loop, "run_subprocess_result", mock)
    with pytest.raises(CreditExhaustedError):
        await loop._repo_probe("a/b")


async def test_repair_prunes_first_404_entry(tmp_path: Path) -> None:
    good = ManagedRepo(slug="good/repo")
    bad = ManagedRepo(slug="bad/repo")
    loop, _prs, _state, cfg = _real_loop(tmp_path, managed_repos=[good, bad])

    async def fake_probe(slug: str) -> bool | None:
        return slug != "bad/repo"

    loop._repo_probe = fake_probe  # type: ignore[method-assign]
    result = await loop._repair_principles_audit_404_repo()
    assert result == "bad/repo"
    enabled_by_slug = {mr.slug: mr.enabled for mr in cfg.managed_repos}
    assert enabled_by_slug == {"good/repo": True, "bad/repo": False}


async def test_repair_skips_already_disabled_entries(tmp_path: Path) -> None:
    disabled_bad = ManagedRepo(slug="bad/repo", enabled=False)
    loop, _prs, _state, _cfg = _real_loop(tmp_path, managed_repos=[disabled_bad])
    probe_calls: list[str] = []

    async def fake_probe(slug: str) -> bool | None:
        probe_calls.append(slug)
        return False

    loop._repo_probe = fake_probe  # type: ignore[method-assign]
    result = await loop._repair_principles_audit_404_repo()
    assert result is None
    assert probe_calls == []


async def test_repair_all_healthy_returns_none(tmp_path: Path) -> None:
    good = ManagedRepo(slug="good/repo")
    loop, _prs, _state, cfg = _real_loop(tmp_path, managed_repos=[good])

    async def fake_probe(_slug: str) -> bool | None:
        return True

    loop._repo_probe = fake_probe  # type: ignore[method-assign]
    result = await loop._repair_principles_audit_404_repo()
    assert result is None
    assert cfg.managed_repos[0].enabled is True


async def test_end_to_end_principles_audit_repair_via_actuator(
    tmp_path: Path,
) -> None:
    """Full path: 3 consecutive `error` heartbeats for `principles_audit`
    trips the actuator, which finds and prunes the 404'd entry — no issue
    filed for a repo that self-healed."""
    good = ManagedRepo(slug="good/repo")
    bad = ManagedRepo(slug="bad/repo")
    loop, prs, state, cfg = _real_loop(tmp_path, managed_repos=[good, bad])

    async def fake_probe(slug: str) -> bool | None:
        return slug != "bad/repo"

    loop._repo_probe = fake_probe  # type: ignore[method-assign]
    state.set_worker_heartbeat("principles_audit", _hb("error"))

    for _ in range(_ERROR_STREAK_THRESHOLD):
        await loop._check_persistent_worker_errors()

    enabled_by_slug = {mr.slug: mr.enabled for mr in cfg.managed_repos}
    assert enabled_by_slug == {"good/repo": True, "bad/repo": False}
    prs.create_issue.assert_not_awaited()
