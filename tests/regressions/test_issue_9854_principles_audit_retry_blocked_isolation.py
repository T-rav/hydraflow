"""Regression: PrinciplesAuditLoop._retry_blocked isolates a failing repo.

Context (#9854 groom / #9792 outage): the motivating outage included an
uncaught crash where ``_retry_blocked`` called ``await
self._audit_managed_repo(mr)`` for every blocked slug with no per-target
guard, so a single blocked-onboarding repo that 404'd raised out of the whole
tick every cycle — pegging ``tick_error_ratio`` at 1.0 and feeding the
principles_audit anomaly->epic runaway. The per-target isolation fix landed via
#9855/#9805 (PR #9971); this pins that behavior so it can't silently regress.

Invariant: when auditing one blocked repo raises a transient failure
(``RuntimeError`` — e.g. a gh 404, NOT a code bug), ``_retry_blocked`` must
- swallow it (no exception escapes the sweep), and
- keep processing the remaining blocked repos, flipping a healthy one to
  ``ready``.

Sibling ``_reconcile_onboarding`` shares the same guard; this incident pin
targets the exact call the groom named. The all-loops resilience contract lives
in ``tests/scenarios/test_loop_health.py``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from base_background_loop import LoopDeps
from config import HydraFlowConfig, ManagedRepo
from events import EventBus
from principles_audit_loop import PrinciplesAuditLoop


def _deps() -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


def _blocked_loop(tmp_path: Path) -> tuple[PrinciplesAuditLoop, MagicMock]:
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    # First repo raises when audited; second audits clean and must still flip.
    cfg.managed_repos = [
        ManagedRepo(slug="bad/repo"),
        ManagedRepo(slug="good/repo"),
    ]
    state = MagicMock()
    state.get_onboarding_status.return_value = "blocked"  # both blocked
    loop = PrinciplesAuditLoop(
        config=cfg, state=state, pr_manager=AsyncMock(), deps=_deps()
    )
    return loop, state


async def test_retry_blocked_isolates_failing_repo(tmp_path: Path) -> None:
    loop, state = _blocked_loop(tmp_path)

    async def fake_audit(mr: ManagedRepo) -> dict[str, str]:
        if mr.slug == "bad/repo":
            # Transient external failure (a gh 404), not a code bug — must be
            # isolated, not re-raised, and must not abort the sweep.
            raise RuntimeError("gh api: 404 Not Found for bad/repo")
        return {"P1.1": "PASS"}

    async def fake_report(_mr: ManagedRepo) -> dict[str, Any]:
        return {"findings": []}

    loop._audit_managed_repo = fake_audit  # type: ignore[method-assign]
    loop._fetch_last_report = fake_report  # type: ignore[method-assign]
    loop._p1_p5_fails = lambda _findings: []  # type: ignore[method-assign,assignment]

    # Must NOT raise despite bad/repo's 404 — a bare `await` here would fail.
    flipped = await loop._retry_blocked()

    # The healthy repo still flipped; the failing one did not abort the sweep.
    assert flipped == 1
    flip_calls = [
        c.args
        for c in state.set_onboarding_status.call_args_list
        if len(c.args) >= 2 and c.args[1] == "ready"
    ]
    assert flip_calls == [("good/repo", "ready")]


async def test_retry_blocked_all_failing_returns_zero_without_raising(
    tmp_path: Path,
) -> None:
    loop, state = _blocked_loop(tmp_path)

    async def fake_audit(_mr: ManagedRepo) -> dict[str, str]:
        raise RuntimeError("gh api: 404 Not Found")

    loop._audit_managed_repo = fake_audit  # type: ignore[method-assign]

    flipped = await loop._retry_blocked()

    assert flipped == 0
    # No slug was flipped to ready when every audit failed.
    assert not [
        c
        for c in state.set_onboarding_status.call_args_list
        if len(c.args) >= 2 and c.args[1] == "ready"
    ]
