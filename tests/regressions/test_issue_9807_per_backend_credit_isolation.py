"""Regression: a Claude credit cap globally halted z.ai/kimi background workers,
and a backend cap globally halted Claude work (#9807).

Before per-backend isolation, ``_pause_for_credits`` cancelled EVERY loop on any
corroborated ``CreditExhaustedError``, regardless of which backend hit the
limit. A single spurious/real Claude cap therefore idled the whole factory —
including loops whose operator had deliberately routed them to z.ai/kimi to
survive exactly that.

The fix classifies the signal's ``provider`` and scopes the pause to loops
routed there:
  * an Anthropic cap pauses the harness loops but SPARES backend-routed loops;
  * a z.ai/kimi cap pauses only its own loops and leaves Claude work + the
    shared harness runner pools running.

These tests pin both directions through the real ``_pause_for_credits``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from orchestrator import HydraFlowOrchestrator
from subprocess_util import CreditExhaustedError
from tests.helpers import ConfigFactory


async def _noop_loop() -> None:
    await asyncio.sleep(0)


def _make_orch(**dials):
    """Orchestrator with the pause machinery below the classifier stubbed so the
    test exercises only the scoping decision. *dials* set ``*_provider`` fields."""
    config = ConfigFactory.create().model_copy(update=dials)
    orch = HydraFlowOrchestrator(config)
    orch._cancel_all_loops_and_runners = AsyncMock()  # type: ignore[method-assign]
    orch._sleep_until_resume = AsyncMock()  # type: ignore[method-assign]
    orch._resume_loops_after_credit_pause = AsyncMock()  # type: ignore[method-assign]
    return orch


_TASKS = {"plan": None, "review": None, "repo_wiki": None, "store": None}
_FACTORIES = [(name, _noop_loop) for name in _TASKS]


@pytest.mark.asyncio
async def test_anthropic_cap_spares_kimi_routed_worker() -> None:
    """A Claude cap must NOT cancel the kimi-routed wiki loop (the reported bug)."""
    orch = _make_orch(wiki_compilation_provider="kimi")
    exc = CreditExhaustedError("usage limit reached")  # provider defaults anthropic

    with patch("orchestrator_credits.probe_credit_availability", AsyncMock(return_value=False)):
        paused = await orch._pause_for_credits(exc, "plan", dict(_TASKS), _FACTORIES)

    assert paused is True
    assert orch._credit_paused_provider == "anthropic"
    affected, kwargs = _cancel_call(orch)
    assert "repo_wiki" not in affected  # kimi worker survives the Claude cap
    assert {"plan", "review", "store"} <= affected
    assert kwargs["terminate_runners"] is True


@pytest.mark.asyncio
async def test_backend_cap_scopes_to_backend_and_spares_harness() -> None:
    """A kimi cap pauses only kimi loops; Claude loops + harness pools survive."""
    orch = _make_orch(wiki_compilation_provider="kimi")
    exc = CreditExhaustedError("kimi 429: rate limit", provider="kimi")

    with patch("orchestrator_credits.probe_credit_availability", AsyncMock(return_value=False)):
        paused = await orch._pause_for_credits(
            exc, "repo_wiki", dict(_TASKS), _FACTORIES
        )

    assert paused is True
    assert orch._credit_paused_provider == "kimi"
    affected, kwargs = _cancel_call(orch)
    assert affected == {"repo_wiki"}
    assert kwargs["terminate_runners"] is False  # Anthropic runner pools untouched
    # Resume is scoped to the same set.
    resume_args = orch._resume_loops_after_credit_pause.await_args
    assert resume_args.args[3] == {"repo_wiki"}


@pytest.mark.asyncio
async def test_backend_probe_targets_the_affected_backend() -> None:
    """The corroborating probe hits the AFFECTED backend, not always Anthropic."""
    orch = _make_orch(wiki_compilation_provider="zai")
    exc = CreditExhaustedError("zai 402", provider="zai")

    probe = AsyncMock(return_value=False)
    with patch("orchestrator_credits.probe_credit_availability", probe):
        await orch._pause_for_credits(exc, "repo_wiki", dict(_TASKS), _FACTORIES)

    # Probed with provider="zai" (positional) rather than the Anthropic default.
    assert probe.await_args.args[0] == "zai"


@pytest.mark.asyncio
async def test_backend_false_positive_does_not_pause_claude() -> None:
    """A refuted backend signal pauses nothing (and reports not-paused for the
    caller to restart the crashed loop) — Claude work is never touched."""
    orch = _make_orch(wiki_compilation_provider="zai")
    exc = CreditExhaustedError("zai quoted prose", provider="zai")

    with patch("orchestrator_credits.probe_credit_availability", AsyncMock(return_value=True)):
        paused = await orch._pause_for_credits(
            exc, "repo_wiki", dict(_TASKS), _FACTORIES
        )

    assert paused is False
    assert orch._credits_paused_until is None
    orch._cancel_all_loops_and_runners.assert_not_awaited()


def _cancel_call(orch) -> tuple[set[str], dict]:
    """Extract (affected, kwargs) from the recorded _cancel_all_loops_and_runners call."""
    call = orch._cancel_all_loops_and_runners.await_args
    # Signature: (tasks, affected, *, terminate_runners=...)
    affected = call.args[1] if len(call.args) > 1 else call.kwargs["affected"]
    return affected, call.kwargs
