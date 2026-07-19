"""Regression: DiscoverRunner wedged the sandbox discover loop (#9796/#9867).

Every rc/* promotion since s51's introduction failed because
``DiscoverRunner._run_discovery_once`` had NO MockWorld bypass: with the
``_mockworld_fake_llm`` sentinel attached (docker sandbox, air-gapped
network) it still spawned a real ``claude -p`` subprocess via
``BaseRunner._execute``, which blocked for the full ``agent_timeout``.
The discover phase loop wedged mid-tick (frozen ``last_run`` heartbeat),
the issue never reached plan, and s51's two-LOOP-BACK oscillation
snapshot never formed. ``_evaluate_brief`` had the same exposure when a
scenario seeded no ``discover`` script (bypass returned None → real
subprocess dispatch).

These tests pin the sentinel contract: with ``_mockworld_fake_llm``
attached, ``DiscoverRunner`` must NEVER dispatch a subprocess — the
discovery pass returns a deterministic stub brief and an unscripted
evaluator fails open. Scripted coherence verdicts keep working.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from discover_runner import DiscoverRunner
from events import EventBus
from models import Task


def _make_task(issue_id: int = 1) -> Task:
    return Task(
        id=issue_id,
        title="Investigate recurring churn in auth module",
        body="Needs discovery first.",
        tags=[],
        comments=[],
        source_url="",
        links=[],
        complexity_score=0,
        created_at="",
        metadata={},
    )


class _FakeLLMSentinel:
    """Minimal stand-in for mockworld.fakes.fake_llm.FakeLLM."""

    _is_fake_adapter = True

    def __init__(self, scripted: list[object] | None = None) -> None:
        self._scripted = list(scripted or [])

    def pop_discover_script(self, issue_number: int) -> object | None:
        _ = issue_number
        if self._scripted:
            return self._scripted.pop(0)
        return None


def _make_runner(config, *, max_attempts: int = 2) -> DiscoverRunner:
    config.max_discover_attempts = max_attempts
    config.max_discover_expansions = 0
    config.repo_root = Path("/tmp")
    config.dry_run = False
    runner = DiscoverRunner(config=config, event_bus=MagicMock(spec=EventBus))
    # Any subprocess dispatch under the sentinel is the regression.
    runner._execute = AsyncMock(  # type: ignore[method-assign]
        side_effect=AssertionError(
            "DiscoverRunner dispatched a subprocess despite the "
            "_mockworld_fake_llm sentinel — this wedges the air-gapped sandbox"
        )
    )
    return runner


@pytest.mark.asyncio
async def test_discover_never_spawns_subprocess_under_sentinel(config) -> None:
    """Sentinel attached → discover() completes with a stub brief, zero spawns."""
    runner = _make_runner(config)
    runner._mockworld_fake_llm = _FakeLLMSentinel()  # type: ignore[attr-defined]

    result = await runner.discover(_make_task())

    assert result.research_brief  # deterministic stub, never empty
    runner._execute.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_unscripted_evaluator_fails_open_under_sentinel(config) -> None:
    """No scripted coherence verdict → evaluator passes without dispatching."""
    runner = _make_runner(config)
    runner._mockworld_fake_llm = _FakeLLMSentinel()  # type: ignore[attr-defined]

    passed, summary, findings = await runner._evaluate_brief(_make_task(), "stub brief")

    assert passed is True
    assert findings == []
    assert summary  # explains the fail-open so operators can grep it
    runner._execute.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_scripted_coherence_failure_still_consumed_under_sentinel(
    config,
) -> None:
    """A seeded coherence rejection still drives the retry path unchanged."""
    from mockworld.fakes.fake_llm import FakeLLM

    fake = FakeLLM()
    fake.script_discover(
        1,
        coherent=False,
        queries_required=[],
        summary="scripted coherence rejection",
        findings=["missing user research"],
    )
    runner = _make_runner(config)
    runner._mockworld_fake_llm = fake  # type: ignore[attr-defined]

    passed, summary, findings = await runner._evaluate_brief(_make_task(), "stub brief")

    assert passed is False
    assert summary == "scripted coherence rejection"
    assert findings == ["missing user research"]
    runner._execute.assert_not_awaited()  # type: ignore[attr-defined]
