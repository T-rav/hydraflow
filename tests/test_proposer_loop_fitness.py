"""Tests: TermProposerLoop and EdgeProposerLoop report SCORED fitness via
``proposal_acceptance_fitness``; GateActivatorLoop reports HOUSEKEEPING.

For TermProposerLoop and EdgeProposerLoop:
- Build with the real constructor (config from ConfigFactory, MagicMock/AsyncMock
  for collaborators that only call loop_fitness via self._config / self._worker_name).
- Craft a FitnessContext with 3 records carrying the loop's label, 2 accepted.
- Assert kind==SCORED, confidence==OK, score==approx(2/3), components correct.

For GateActivatorLoop:
- GateActivatorLoop files ONE stable-titled, deduped issue and closes it itself
  (_resolve_activation_issue) when no proposals remain. Closed issues reflect the
  loop's own housekeeping, not human acceptance -- no honest per-proposal signal
  exists. Assert kind==HOUSEKEEPING, score is None.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from loop_fitness import Confidence, FitnessContext, FitnessKind, IssueRecord
from tests.helpers import ConfigFactory

_WINDOW_START = datetime(2026, 6, 1, tzinfo=UTC)
_WINDOW_END = datetime(2026, 6, 30, tzinfo=UTC)
_CREATED_AT = datetime(2026, 6, 10, tzinfo=UTC)


def _deps() -> LoopDeps:
    return LoopDeps(
        event_bus=MagicMock(),
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=MagicMock(return_value=True),
        sleep_fn=AsyncMock(),
    )


def _pr_ctx(label: str) -> FitnessContext:
    """3 PRs with the given label, 2 merged."""
    return FitnessContext(
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        issues=[
            IssueRecord(
                number=i,
                labels=[label],
                is_pr=True,
                merged=(i < 2),
                created_at=_CREATED_AT,
            )
            for i in range(3)
        ],
    )


def _issue_ctx(label: str) -> FitnessContext:
    """3 issues with the given label, 2 closed."""
    return FitnessContext(
        window_start=_WINDOW_START,
        window_end=_WINDOW_END,
        issues=[
            IssueRecord(
                number=i,
                labels=[label],
                is_pr=False,
                state="closed" if i < 2 else "open",
                created_at=_CREATED_AT,
            )
            for i in range(3)
        ],
    )


def test_term_proposer_reports_scored_fitness(tmp_path: Path) -> None:
    from term_proposer_loop import TERM_PROPOSER_PR_LABEL, TermProposerLoop

    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        fitness_min_samples=2,
    )
    loop = TermProposerLoop(
        config=config,
        deps=_deps(),
        llm=MagicMock(),
        pr_port=AsyncMock(),
        repo_root=tmp_path / "repo",
        dedup_path=tmp_path / "dedup.json",
    )

    fit = loop.loop_fitness(_pr_ctx(TERM_PROPOSER_PR_LABEL))

    assert fit.kind is FitnessKind.SCORED
    assert fit.confidence is Confidence.OK
    assert fit.score == pytest.approx(2 / 3)
    assert fit.components == {"filed": 3.0, "accepted": 2.0}
    assert fit.worker_name == "term_proposer"


def test_edge_proposer_reports_scored_fitness(tmp_path: Path) -> None:
    from edge_proposer_loop import EDGE_PROPOSER_PR_LABEL, EdgeProposerLoop

    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        fitness_min_samples=2,
    )
    loop = EdgeProposerLoop(
        config=config,
        deps=_deps(),
        pr_port=AsyncMock(),
        repo_root=tmp_path / "repo",
    )

    fit = loop.loop_fitness(_pr_ctx(EDGE_PROPOSER_PR_LABEL))

    assert fit.kind is FitnessKind.SCORED
    assert fit.confidence is Confidence.OK
    assert fit.score == pytest.approx(2 / 3)
    assert fit.components == {"filed": 3.0, "accepted": 2.0}
    assert fit.worker_name == "edge_proposer"


def test_gate_activator_reports_housekeeping_fitness(tmp_path: Path) -> None:
    """GateActivatorLoop must return HOUSEKEEPING -- not SCORED.

    The loop closes its own issue via _resolve_activation_issue when no
    proposals remain, so "closed" reflects housekeeping, not human acceptance.
    There is no honest per-proposal acceptance signal for this loop.
    """
    from dedup_store import DedupStore
    from gate_activator_loop import GateActivatorLoop

    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        fitness_min_samples=2,
    )
    dedup = DedupStore(set_name="gate_activator", file_path=tmp_path / "dedup.json")
    loop = GateActivatorLoop(
        config,
        AsyncMock(),
        dedup,
        _deps(),
        detector=AsyncMock(return_value=[]),
    )

    # Context doesn't matter for HOUSEKEEPING; use an issue ctx for completeness.
    label = "hydraflow-gate-activation"
    fit = loop.loop_fitness(_issue_ctx(label))

    assert fit.kind is FitnessKind.HOUSEKEEPING
    assert fit.score is None
    assert fit.worker_name == "gate_activator"
