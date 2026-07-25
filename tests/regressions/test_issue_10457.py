"""Regression: fleet-batch ADR-drift dedup-skip must actually exclude a
re-triage, not just leave the guard present but unreachable (#10457).

The prior attempt at this issue (#10411) stalled test-adequacy on exactly
this edge case: a ``FLEET-<pr>`` batch already fingerprinted in the dedup
store must be excluded from ``AdrDriftResolverLoop._fleet_candidates`` on
the NEXT tick, so it is never re-triaged (no wasted LLM calls, no risk of
flip-flopping a decision a human may have already acted on). This pins that
behavior against REAL ``StateTracker``/``DedupStore`` instances (not mocks)
so a future refactor of either can't silently reintroduce the gap.

Uses a contrast pair: the SAME fleet rollup is dedup-skipped when already
fingerprinted, and — with no dedup mark — is triaged and closed normally.
Only asserting the skip case would not prove the guard actually
discriminates between "seen" and "unseen"; the second test does.
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

_ISSUE_NUMBER = 77
_PR_NUMBER = 9603
_FLEET_KEY = "FLEET-9603"
_FLEET_DEDUP_KEY = f"adr_drift_resolver:{_FLEET_KEY}:{_ISSUE_NUMBER}"


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
    tmp_path: Path,
) -> tuple[AdrDriftResolverLoop, StateTracker, DedupStore, AsyncMock, AsyncMock]:
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    _write_adr(adr_dir, number=24, title="alpha", related="src/agent.py")
    _write_adr(adr_dir, number=27, title="beta", related="src/runner.py")

    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        repo_root=tmp_path,
        # Loop now defaults OFF (#10540); force ON for this regression pin.
        adr_drift_resolver_loop_enabled=True,
    )
    state = StateTracker(tmp_path / "state.json")
    dedup = DedupStore("adr_drift_resolver", tmp_path / "dedup.json")

    state.set_adr_rollup(
        _FLEET_KEY,
        issue_number=_ISSUE_NUMBER,
        pr_numbers=[_PR_NUMBER],
        adr_numbers=[24, 27],
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


async def test_already_fingerprinted_fleet_batch_is_excluded_from_retriage(
    tmp_path: Path,
) -> None:
    """The dedup-skip edge case flagged by test-adequacy on the prior
    attempt: a FLEET-<pr> batch already in the (real) dedup store is not
    re-triaged."""
    loop, state, dedup, pr, triage = _make_loop(tmp_path)
    dedup.add(_FLEET_DEDUP_KEY)

    result = await loop._do_work()

    assert result["fleet_candidates"] == 0
    assert result["fleet_triaged"] == 0
    triage.classify.assert_not_called()
    pr.close_issue.assert_not_called()
    # The dedup store itself still carries only the pre-existing mark — the
    # skip did not spuriously add or remove anything.
    assert dedup.get() == {_FLEET_DEDUP_KEY}


async def test_fleet_batch_without_dedup_mark_is_triaged_and_closed(
    tmp_path: Path,
) -> None:
    """Contrast case: the SAME rollup, with no dedup fingerprint yet, IS
    triaged this tick and marks dedup on a definitive (closed) outcome —
    proving the skip in the test above is a real discriminator, not a
    guard that always fires."""
    loop, state, dedup, pr, triage = _make_loop(tmp_path)
    triage.classify = AsyncMock(
        side_effect=[
            TriageVerdict(
                classification=DriftClassification.CONSISTENT,
                rationale="alpha unaffected",
            ),
            TriageVerdict(
                classification=DriftClassification.CONSISTENT,
                rationale="beta unaffected",
            ),
        ]
    )

    result = await loop._do_work()

    assert result["fleet_candidates"] == 1
    assert result["fleet_closed"] == 1
    pr.close_issue.assert_awaited_once_with(_ISSUE_NUMBER, reason="not planned")
    assert dedup.get() == {_FLEET_DEDUP_KEY}


async def test_dedup_skip_holds_across_a_fresh_loop_instance(tmp_path: Path) -> None:
    """The skip is durable via the on-disk dedup store, not an in-memory
    fluke of reusing the same loop object across ticks."""
    loop, state, dedup, pr, triage = _make_loop(tmp_path)
    triage.classify = AsyncMock(
        side_effect=[
            TriageVerdict(
                classification=DriftClassification.CONSISTENT, rationale="alpha"
            ),
            TriageVerdict(
                classification=DriftClassification.CONSISTENT, rationale="beta"
            ),
        ]
    )
    first = await loop._do_work()
    assert first["fleet_closed"] == 1

    # A brand new loop instance reading the SAME on-disk state/dedup files
    # must still see the batch as already-triaged.
    second_loop, _, _, second_pr, second_triage = _make_loop(tmp_path)
    second_result = await second_loop._do_work()

    assert second_result["fleet_candidates"] == 0
    second_triage.classify.assert_not_called()
