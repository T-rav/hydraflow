"""Regression: AdrDriftResolverLoop's shared per-tick LLM-call budget must
count every call ATTEMPTED (success + error), not just successful triages
(#11181).

A fresh adversarial re-audit of the already-merged #10474 fleet-triage
budget gate found that ``triaged`` (bumped only after a successful
``classify()`` call, src/adr_drift_resolver_loop.py) undercounts the tick's
real LLM-call volume whenever a triage call errors — the call was still
made (a real spend), it just raised. The fleet gate computed
``remaining_budget = max_per_tick - (triaged + fleet_calls_spent)``, so an
error-heavy tick could make the gate think there was more room than there
really was, letting a fleet batch (which can spend one call PER member ADR)
start and overshoot ``adr_drift_resolver_max_triage_per_tick`` — directly
contradicting the module docstring's guarantee that an overshooting batch
is "deferred whole to next tick rather than starting it."

The fix threads a separate ``calls_spent`` counter (attempts, not
successes) through both the per-ADR loop's own cap and the fleet gate, and
``_triage_fleet_batch`` now returns ``(outcome, calls_spent)`` reflecting
the calls it ACTUALLY attempted — not ``len(adr_numbers)`` — so a
partial-error batch reports its true spend to the next candidate's budget
check.

Uses a contrast pair (mirrors ``test_issue_10457.py``): the SAME fleet
batch is deferred when per-ADR errors have exhausted the tick's budget, and
— with one more call of room — is triaged and closed normally. Only
asserting the deferral case would not prove the gate actually discriminates
on remaining budget; the second test does. Pins against REAL
``StateTracker``/``DedupStore`` instances (not mocks) so a future refactor
of either can't silently reintroduce the gap.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from adr_drift_resolver_loop import AdrDriftResolverLoop
from adr_drift_triage import DriftClassification, TriageVerdict
from adr_index import ADRIndex
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from events import EventBus
from state import StateTracker

_FLEET_ISSUE_NUMBER = 77
_FLEET_PR_NUMBER = 9603
_FLEET_KEY = "FLEET-9603"
_FLEET_DEDUP_KEY = f"adr_drift_resolver:{_FLEET_KEY}:{_FLEET_ISSUE_NUMBER}"


def _write_adr(adr_dir: Path, *, number: int, title: str, related: str) -> None:
    body = (
        f"# ADR-{number:04d}: {title}\n\n"
        f"- **Status:** Accepted\n"
        f"- **Date:** 2026-01-01\n"
        f"- **Related:** `{related}`\n\n"
        f"## Context\n\nFixture background.\n\n"
        f"## Decision\n\nFixture decision text.\n"
    )
    (adr_dir / f"{number:04d}-{title}.md").write_text(body)


def _make_loop(
    tmp_path: Path, *, max_per_tick: int
) -> tuple[AdrDriftResolverLoop, StateTracker, DedupStore, AsyncMock, AsyncMock]:
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    _write_adr(adr_dir, number=24, title="alpha", related="src/agent.py")
    _write_adr(adr_dir, number=27, title="beta", related="src/runner.py")
    _write_adr(adr_dir, number=30, title="gamma", related="src/state.py")

    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        repo_root=tmp_path,
        # Loop now defaults OFF (#10540); force ON for this regression pin.
        adr_drift_resolver_loop_enabled=True,
        adr_drift_resolver_max_triage_per_tick=max_per_tick,
    )
    state = StateTracker(tmp_path / "state.json")
    dedup = DedupStore("adr_drift_resolver", tmp_path / "dedup.json")

    # 2 per-ADR candidates that will both error, plus 1 fleet batch (1
    # member ADR) competing for the SAME tick's LLM-call budget.
    state.set_adr_rollup("ADR-0024", issue_number=42, pr_numbers=[8473])
    state.set_adr_rollup("ADR-0027", issue_number=43, pr_numbers=[8474])
    state.set_adr_rollup(
        _FLEET_KEY,
        issue_number=_FLEET_ISSUE_NUMBER,
        pr_numbers=[_FLEET_PR_NUMBER],
        adr_numbers=[30],
    )

    pr = AsyncMock()
    pr.get_pr_diff = AsyncMock(
        return_value="diff --git a/src/agent.py b/src/agent.py\n"
        "@@ -1,1 +1,1 @@\n-# old\n+# refactor only\n"
    )
    pr.get_issue_labels = AsyncMock(return_value=["hydraflow-adr-drift"])
    pr.post_comment = AsyncMock(return_value=None)
    pr.close_issue = AsyncMock(return_value=True)

    triage = AsyncMock()

    loop = AdrDriftResolverLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=ADRIndex(adr_dir),
        triage=triage,
        deps=LoopDeps(
            event_bus=EventBus(),
            stop_event=asyncio.Event(),
            status_cb=lambda *a, **k: None,
            enabled_cb=lambda _name: True,
        ),
    )
    return loop, state, dedup, pr, triage


async def test_per_adr_triage_errors_exhaust_budget_and_defer_fleet_batch(
    tmp_path: Path,
) -> None:
    """The exact escape from #11181: 2 per-ADR candidates (ADR-0024,
    ADR-0027) both hit a triage-call error with max_per_tick=2 — 2 real
    calls spent, ``triaged`` stays 0. The competing fleet batch (1 member,
    ADR-0030) needs 1 more call than the tick has left and must be
    deferred whole, never spending a 3rd call this tick."""
    loop, state, dedup, pr, triage = _make_loop(tmp_path, max_per_tick=2)
    triage.classify = AsyncMock(
        side_effect=[
            RuntimeError("llm call failed"),
            RuntimeError("llm call failed"),
            # Only reached if the gate is still buggy — kept so a
            # regression fails on the clean assertions below instead of an
            # unhandled StopIteration.
            TriageVerdict(
                classification=DriftClassification.CONSISTENT,
                rationale="fleet member ok",
            ),
        ]
    )

    result = await loop._do_work()

    assert result["errors"] == 2
    assert result["triaged"] == 0
    assert result["fleet_candidates"] == 1
    assert result["fleet_triaged"] == 0
    assert result["fleet_closed"] == 0
    assert triage.classify.await_count == 2
    pr.close_issue.assert_not_called()
    assert dedup.get() == set()


async def test_fleet_batch_runs_when_budget_has_room_after_per_adr_errors(
    tmp_path: Path,
) -> None:
    """Contrast case: the SAME fleet batch, with max_per_tick=3 (one more
    call of room than the 2 per-ADR errors consume), IS triaged and closes
    normally — proving the deferral above is a real budget effect, not a
    fleet path that always blocks after any per-ADR error."""
    loop, state, dedup, pr, triage = _make_loop(tmp_path, max_per_tick=3)
    triage.classify = AsyncMock(
        side_effect=[
            RuntimeError("llm call failed"),
            RuntimeError("llm call failed"),
            TriageVerdict(
                classification=DriftClassification.CONSISTENT,
                rationale="fleet member ok",
            ),
        ]
    )

    result = await loop._do_work()

    assert result["errors"] == 2
    assert result["fleet_candidates"] == 1
    assert result["fleet_triaged"] == 1
    assert result["fleet_closed"] == 1
    assert triage.classify.await_count == 3
    pr.close_issue.assert_awaited_once_with(_FLEET_ISSUE_NUMBER, reason="not planned")
    assert dedup.get() == {_FLEET_DEDUP_KEY}
