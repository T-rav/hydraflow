"""apply_decision widened-intake transitions (#9721).

When ``hitl_widened=True`` the issue arrived via the widened
``hydraflow-hitl`` intake and is currently claimed under
``hydraflow-hitl-autofix``. The resolver owns the transition (mirrors
``HITLPhase``): a resolve returns the issue to its origin stage and resets
attempt state; a terminal outcome returns it to the human queue.
``hitl_widened=False`` must stay byte-for-byte today's behavior.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from preflight.decision import PreflightResult, apply_decision


def _result(status: str, **kwargs) -> PreflightResult:
    return PreflightResult(
        status=status,
        pr_url=kwargs.get("pr_url"),
        diagnosis=kwargs.get("diagnosis", "diag"),
        cost_usd=kwargs.get("cost_usd", 1.0),
        wall_clock_s=kwargs.get("wall_clock_s", 60.0),
        tokens=kwargs.get("tokens", 1000),
    )


def _config(hitl: str = "hydraflow-hitl", ready: str = "hydraflow-ready"):
    config = MagicMock()
    config.hitl_label = [hitl]
    config.ready_label = [ready]
    return config


def _state(attempts: int = 1) -> MagicMock:
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=attempts)
    return state


@pytest.mark.asyncio
async def test_widened_resolved_swaps_to_origin_and_resets_state() -> None:
    pr = AsyncMock()
    state = _state()
    out = await apply_decision(
        issue_number=42,
        sub_label="implement-cap-exhausted",
        result=_result("resolved", pr_url="https://x/pr/1"),
        pr_port=pr,
        state=state,
        max_attempts=3,
        config=_config(),
        hitl_widened=True,
        origin_label="hydraflow-ready",
    )
    pr.swap_pipeline_labels.assert_awaited_once_with(42, "hydraflow-ready")
    state.reset_issue_attempts.assert_called_once_with(42)
    state.remove_hitl_origin.assert_called_once_with(42)
    state.remove_hitl_cause.assert_called_once_with(42)
    pr.add_labels.assert_not_awaited()
    assert out["status"] == "resolved"
    assert out["hitl_widened"] is True


@pytest.mark.asyncio
async def test_widened_resolved_does_not_remove_stem_as_label() -> None:
    """The widened sub_label is a playbook routing stem, not an issue label —
    it must not be pushed into the label-remove set."""
    pr = AsyncMock()
    await apply_decision(
        issue_number=42,
        sub_label="implement-cap-exhausted",
        result=_result("resolved", pr_url="https://x/pr/1"),
        pr_port=pr,
        state=_state(),
        max_attempts=3,
        config=_config(),
        hitl_widened=True,
        origin_label="hydraflow-ready",
    )
    removed = {call.args[1] for call in pr.remove_label.await_args_list}
    assert "implement-cap-exhausted" not in removed


@pytest.mark.asyncio
async def test_widened_resolved_without_origin_targets_ready_label() -> None:
    pr = AsyncMock()
    await apply_decision(
        issue_number=42,
        sub_label="_default",
        result=_result("resolved", pr_url="https://x/pr/1"),
        pr_port=pr,
        state=_state(),
        max_attempts=3,
        config=_config(ready="custom-ready"),
        hitl_widened=True,
        origin_label=None,
    )
    pr.swap_pipeline_labels.assert_awaited_once_with(42, "custom-ready")


@pytest.mark.asyncio
async def test_widened_terminal_returns_to_hitl_before_human_required() -> None:
    """Terminal outcomes swap the claim back to hydraflow-hitl FIRST — the
    swap clears human-required (it's in all_pipeline_labels), so adding it
    must happen after."""
    pr = AsyncMock()
    order: list[str] = []

    async def _swap(issue: int, label: str, **_kw) -> None:
        order.append(f"swap:{label}")

    async def _add(issue: int, labels: list[str]) -> None:
        order.append(f"add:{','.join(labels)}")

    pr.swap_pipeline_labels = AsyncMock(side_effect=_swap)
    pr.add_labels = AsyncMock(side_effect=_add)
    state = _state()
    await apply_decision(
        issue_number=42,
        sub_label="implement-cap-exhausted",
        result=_result("needs_human"),
        pr_port=pr,
        state=state,
        max_attempts=3,
        config=_config(),
        hitl_widened=True,
        origin_label="hydraflow-ready",
    )
    assert order == ["swap:hydraflow-hitl", "add:human-required"]
    state.reset_issue_attempts.assert_not_called()


@pytest.mark.asyncio
async def test_widened_retry_keeps_claim_when_budget_remains() -> None:
    """A recoverable bail stays claimed under the autofix label so the next
    tick re-attempts without a human ever seeing the issue."""
    pr = AsyncMock()
    await apply_decision(
        issue_number=42,
        sub_label="implement-cap-exhausted",
        result=_result("retry"),
        pr_port=pr,
        state=_state(attempts=1),
        max_attempts=3,
        config=_config(),
        hitl_widened=True,
        origin_label="hydraflow-ready",
    )
    pr.swap_pipeline_labels.assert_not_awaited()
    pr.add_labels.assert_not_awaited()


@pytest.mark.asyncio
async def test_widened_retry_at_cap_returns_to_hitl_queue() -> None:
    pr = AsyncMock()
    await apply_decision(
        issue_number=42,
        sub_label="implement-cap-exhausted",
        result=_result("retry"),
        pr_port=pr,
        state=_state(attempts=3),
        max_attempts=3,
        config=_config(),
        hitl_widened=True,
        origin_label="hydraflow-ready",
    )
    pr.swap_pipeline_labels.assert_awaited_once_with(42, "hydraflow-hitl")
    pr.add_labels.assert_awaited_with(42, ["human-required", "auto-agent-exhausted"])


@pytest.mark.asyncio
async def test_non_widened_never_calls_swap() -> None:
    """Regression pin: the escalation path's label behavior is unchanged —
    apply_decision without hitl_widened must never touch swap_pipeline_labels."""
    pr = AsyncMock()
    for status in (
        "resolved",
        "retry",
        "needs_human",
        "fatal",
        "pr_failed",
        "cost_exceeded",
        "timeout",
    ):
        await apply_decision(
            issue_number=42,
            sub_label="flaky-test-stuck",
            result=_result(status, pr_url="https://x/pr/1"),
            pr_port=pr,
            state=_state(),
            max_attempts=3,
        )
    pr.swap_pipeline_labels.assert_not_awaited()
