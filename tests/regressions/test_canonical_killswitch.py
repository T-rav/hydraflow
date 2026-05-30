"""Regression: every non-canonical kill-switch loop respects the _enabled_cb gate.

Per ADR-0049, every loop's _do_work must check self._enabled_cb(self._worker_name)
as its FIRST statement. These loops previously used only a raw env-var or static
config check, so the operator's UI toggle could not disable them at runtime — the
WS-1 kill-switch-integrity fix added the in-body gate to cost_budget_watcher,
diagram, pricing_refresh, and entry_evidence. The auto-discovery enforcer is
tests/test_loop_kill_switch_completeness.py.

Each test: instantiate with an enabled_cb that returns False while leaving the
static config gate OPEN, then assert _do_work returns {"status": "disabled"} —
proving the cb gate (not the config gate) is what disabled the loop.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps


def _disabled_deps() -> LoopDeps:
    """Return a LoopDeps whose enabled_cb always returns False."""
    return LoopDeps(
        event_bus=MagicMock(),
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=lambda _name: False,
        sleep_fn=AsyncMock(),
        interval_cb=MagicMock(return_value=300),
    )


# ---------------------------------------------------------------------------
# CostBudgetWatcherLoop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_budget_watcher_disabled_by_enabled_cb() -> None:
    from cost_budget_watcher_loop import CostBudgetWatcherLoop

    config = MagicMock()
    config.cost_budget_watcher_loop_enabled = True  # static gate open; cb gate closed
    loop = CostBudgetWatcherLoop(
        config=config,
        pr_manager=MagicMock(),
        state=MagicMock(),
        deps=_disabled_deps(),
    )
    result = await loop._do_work()
    assert result == {"status": "disabled"}


# ---------------------------------------------------------------------------
# DiagramLoop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diagram_loop_disabled_by_enabled_cb() -> None:
    from diagram_loop import DiagramLoop

    config = MagicMock()
    config.diagram_loop_enabled = True  # static gate open; cb gate closed
    loop = DiagramLoop(
        config=config,
        pr_manager=MagicMock(),
        deps=_disabled_deps(),
    )
    result = await loop._do_work()
    assert result == {"status": "disabled"}


# ---------------------------------------------------------------------------
# PricingRefreshLoop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pricing_refresh_loop_disabled_by_enabled_cb() -> None:
    from pricing_refresh_loop import PricingRefreshLoop

    config = MagicMock()
    config.pricing_refresh_loop_enabled = True  # static gate open; cb gate closed
    loop = PricingRefreshLoop(
        config=config,
        pr_manager=MagicMock(),
        deps=_disabled_deps(),
    )
    result = await loop._do_work()
    assert result == {"status": "disabled"}


# ---------------------------------------------------------------------------
# EntryEvidenceLoop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entry_evidence_loop_disabled_by_enabled_cb(tmp_path: Path) -> None:
    from entry_evidence_loop import EntryEvidenceLoop

    config = MagicMock()
    config.entry_evidence_enabled = True  # static gate is open; cb gate is closed
    loop = EntryEvidenceLoop(
        config=config,
        deps=_disabled_deps(),
        llm=MagicMock(),
        pr_port=MagicMock(),
        repo_root=tmp_path,
        dedup_path=tmp_path / "dedup.json",
    )
    result = await loop._do_work()
    assert result == {"status": "disabled"}


# ---------------------------------------------------------------------------
# EdgeProposerLoop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edge_proposer_loop_disabled_by_enabled_cb(tmp_path: Path) -> None:
    from edge_proposer_loop import EdgeProposerLoop

    config = MagicMock()
    config.edge_proposer_enabled = True  # static gate is open; cb gate is closed
    loop = EdgeProposerLoop(
        config=config,
        deps=_disabled_deps(),
        pr_port=MagicMock(),
        repo_root=tmp_path,
    )
    result = await loop._do_work()
    assert result == {"status": "disabled"}


# ---------------------------------------------------------------------------
# TermProposerLoop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_term_proposer_loop_disabled_by_enabled_cb(tmp_path: Path) -> None:
    from term_proposer_loop import TermProposerLoop

    config = MagicMock()
    config.term_proposer_enabled = True  # static gate is open; cb gate is closed
    config.term_proposer_interval = 86400
    loop = TermProposerLoop(
        config=config,
        deps=_disabled_deps(),
        llm=MagicMock(),
        pr_port=MagicMock(),
        repo_root=tmp_path,
        dedup_path=tmp_path / "dedup.json",
    )
    result = await loop._do_work()
    assert result == {"status": "disabled"}


# ---------------------------------------------------------------------------
# TermPrunerLoop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_term_pruner_loop_disabled_by_enabled_cb(tmp_path: Path) -> None:
    from term_pruner_loop import TermPrunerLoop

    config = MagicMock()
    config.term_pruner_enabled = True  # static gate is open; cb gate is closed
    config.term_pruner_interval = 86400
    loop = TermPrunerLoop(
        config=config,
        deps=_disabled_deps(),
        pr_port=MagicMock(),
        repo_root=tmp_path,
    )
    result = await loop._do_work()
    assert result == {"status": "disabled"}
