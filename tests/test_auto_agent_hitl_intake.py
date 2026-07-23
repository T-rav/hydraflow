"""Widened HITL intake for AutoAgentPreflightLoop (#9721).

The loop historically polled only ``hitl-escalation``. #9721 widens intake to
idle, pipeline-origin ``hydraflow-hitl`` issues (attempt-cap exhaustion and
quality-gate/zero-diff bails from ImplementPhase et al.) so they get an
autonomous attempt before a human is paged. Claiming swaps the issue to
``hydraflow-hitl-autofix`` so it drops out of the human queue and cannot race
``HITLPhase``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from auto_agent_preflight_loop import AutoAgentPreflightLoop
from preflight.agent import PreflightSpawn
from tests.helpers import make_bg_loop_deps

_RESOLVED_OUTPUT = (
    "<status>resolved</status><pr_url>https://x/pr/9</pr_url>"
    "<confidence>high</confidence><diagnosis>fixed</diagnosis>"
)
_NEEDS_HUMAN_OUTPUT = (
    "<status>needs_human</status><confidence>high</confidence>"
    "<blocked_reason>needs_credentials</blocked_reason>"
    "<diagnosis>requires operator credentials</diagnosis>"
)


def _issue(number: int, label_names: list[str], body: str = "b") -> dict:
    return {
        "number": number,
        "body": body,
        "labels": [{"name": name} for name in label_names],
    }


def _make_loop(tmp_path: Path, *, label_map: dict[str, list[dict]] | None = None):
    """Build a loop whose PR port routes list_issues_by_label per label.

    ready_label is pinned to the production default — ConfigFactory's test
    default is ["test-label"], and the origin→playbook mapping keys on it.
    """
    deps = make_bg_loop_deps(tmp_path, ready_label=["hydraflow-ready"])
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=0)
    state.bump_auto_agent_attempts = MagicMock(return_value=1)
    state.clear_auto_agent_attempts = MagicMock()
    state.get_auto_agent_daily_spend = MagicMock(return_value=0.0)
    state.add_auto_agent_daily_spend = MagicMock(return_value=0.0)
    state.get_escalation_context = MagicMock(return_value=None)
    state.get_hitl_origin = MagicMock(return_value=None)
    state.reset_issue_attempts = MagicMock()
    state.remove_hitl_origin = MagicMock()
    state.remove_hitl_cause = MagicMock()

    pr = AsyncMock()
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    pr.list_issue_comments = AsyncMock(return_value=[])
    pr.add_labels = AsyncMock(return_value=None)
    pr.remove_label = AsyncMock(return_value=None)
    pr.post_comment = AsyncMock(return_value=None)
    pr.swap_pipeline_labels = AsyncMock(return_value=None)
    routes = label_map or {}

    async def _route(label: str) -> list[dict]:
        return routes.get(label, [])

    pr.list_issues_by_label = AsyncMock(side_effect=_route)

    audit = MagicMock()
    audit.append = MagicMock()
    audit.daily_spend = MagicMock(return_value=0.0)
    audit.entries_for_issue = MagicMock(return_value=[])

    loop = AutoAgentPreflightLoop(
        config=deps.config,
        state=state,
        pr_manager=pr,
        wiki_store=None,
        audit_store=audit,
        deps=deps.loop_deps,
    )
    return loop, state, pr, audit


def _stub_spawn(loop: AutoAgentPreflightLoop, output: str, calls: list | None = None):
    captured: dict[str, str] = {}

    def _builder(issue: int):
        async def _spawn(prompt: str, worktree_path: str) -> PreflightSpawn:
            if calls is not None:
                calls.append("spawn")
            captured["prompt"] = prompt
            return PreflightSpawn(
                process=None,
                output_text=output,
                cost_usd=0.5,
                tokens=100,
                crashed=False,
            )

        return _spawn

    loop._build_spawn_fn = _builder
    return captured


# ---------------------------------------------------------------------------
# Poll eligibility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_widened_poll_includes_idle_hitl_issue(tmp_path: Path) -> None:
    loop, _state, _pr, _audit = _make_loop(
        tmp_path,
        label_map={"hydraflow-hitl": [_issue(5, ["hydraflow-hitl"])]},
    )
    eligible = await loop._poll_eligible_issues()
    assert [i["number"] for i in eligible] == [5]
    assert eligible[0]["_intake"] == "hitl_widened"


@pytest.mark.asyncio
async def test_widened_poll_includes_claimed_autofix_issue(tmp_path: Path) -> None:
    """A crash mid-attempt leaves the claim label behind; the next tick must
    re-attempt (bounded by the attempt cap) instead of orphaning the issue."""
    loop, _state, _pr, _audit = _make_loop(
        tmp_path,
        label_map={"hydraflow-hitl-autofix": [_issue(6, ["hydraflow-hitl-autofix"])]},
    )
    eligible = await loop._poll_eligible_issues()
    assert [i["number"] for i in eligible] == [6]
    assert eligible[0]["_intake"] == "hitl_widened"


@pytest.mark.asyncio
async def test_widened_poll_excludes_human_required(tmp_path: Path) -> None:
    loop, _state, _pr, _audit = _make_loop(
        tmp_path,
        label_map={"hydraflow-hitl": [_issue(5, ["hydraflow-hitl", "human-required"])]},
    )
    assert await loop._poll_eligible_issues() == []


@pytest.mark.asyncio
async def test_widened_poll_excludes_hitl_active(tmp_path: Path) -> None:
    """A human is already engaged (comment-unlock) — never race HITLPhase."""
    loop, _state, _pr, _audit = _make_loop(
        tmp_path,
        label_map={
            "hydraflow-hitl": [_issue(5, ["hydraflow-hitl", "hydraflow-hitl-active"])]
        },
    )
    assert await loop._poll_eligible_issues() == []


@pytest.mark.asyncio
async def test_widened_poll_excludes_operator_abort_origin(tmp_path: Path) -> None:
    """/abort parks are human-owned, not pipeline-origin — leave them alone."""
    loop, state, _pr, _audit = _make_loop(
        tmp_path,
        label_map={"hydraflow-hitl": [_issue(5, ["hydraflow-hitl"])]},
    )
    state.get_hitl_origin = MagicMock(return_value="operator-abort")
    assert await loop._poll_eligible_issues() == []


@pytest.mark.asyncio
async def test_dual_labelled_issue_polled_once_via_escalation(tmp_path: Path) -> None:
    """hitl-escalation + hydraflow-hitl on one issue → exactly one entry, owned
    by the escalation branch (no double claim / double attempt-bump)."""
    dual = _issue(7, ["hitl-escalation", "hydraflow-hitl"])
    loop, _state, _pr, _audit = _make_loop(
        tmp_path,
        label_map={"hitl-escalation": [dual], "hydraflow-hitl": [dual]},
    )
    eligible = await loop._poll_eligible_issues()
    assert [i["number"] for i in eligible] == [7]
    assert "_intake" not in eligible[0]


@pytest.mark.asyncio
async def test_flag_off_skips_widened_poll(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYDRAFLOW_AUTO_AGENT_HITL_INTAKE_ENABLED", "false")
    loop, _state, pr, _audit = _make_loop(
        tmp_path,
        label_map={"hydraflow-hitl": [_issue(5, ["hydraflow-hitl"])]},
    )
    eligible = await loop._poll_eligible_issues()
    assert eligible == []
    polled = [c.args[0] for c in pr.list_issues_by_label.await_args_list]
    assert polled == ["hitl-escalation"]


@pytest.mark.asyncio
async def test_widened_poll_failure_does_not_break_escalation_intake(
    tmp_path: Path,
) -> None:
    loop, _state, pr, _audit = _make_loop(tmp_path)

    async def _route(label: str) -> list[dict]:
        if label == "hitl-escalation":
            return [_issue(3, ["hitl-escalation", "flaky-test-stuck"])]
        raise RuntimeError("gh down")

    pr.list_issues_by_label = AsyncMock(side_effect=_route)
    eligible = await loop._poll_eligible_issues()
    assert [i["number"] for i in eligible] == [3]


# ---------------------------------------------------------------------------
# Claim / process / resolve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_swaps_to_autofix_before_spawn(tmp_path: Path) -> None:
    loop, state, pr, _audit = _make_loop(
        tmp_path,
        label_map={"hydraflow-hitl": [_issue(5, ["hydraflow-hitl"])]},
    )
    state.get_hitl_origin = MagicMock(return_value="hydraflow-ready")
    calls: list[str] = []

    async def _swap(issue_number: int, new_label: str, **_kw) -> None:
        calls.append(f"swap:{new_label}")

    pr.swap_pipeline_labels = AsyncMock(side_effect=_swap)
    _stub_spawn(loop, _RESOLVED_OUTPUT, calls)

    result = await loop._do_work()
    assert result["result_status"] == "resolved"
    assert calls.index("swap:hydraflow-hitl-autofix") < calls.index("spawn")


@pytest.mark.asyncio
async def test_widened_resolved_returns_issue_to_origin(tmp_path: Path) -> None:
    loop, state, pr, _audit = _make_loop(
        tmp_path,
        label_map={"hydraflow-hitl": [_issue(5, ["hydraflow-hitl"])]},
    )
    state.get_hitl_origin = MagicMock(return_value="hydraflow-ready")
    _stub_spawn(loop, _RESOLVED_OUTPUT)

    await loop._do_work()

    pr.swap_pipeline_labels.assert_any_await(5, "hydraflow-hitl-autofix")
    pr.swap_pipeline_labels.assert_any_await(5, "hydraflow-ready")
    state.reset_issue_attempts.assert_called_once_with(5)
    state.remove_hitl_origin.assert_called_once_with(5)
    state.remove_hitl_cause.assert_called_once_with(5)
    for call in pr.add_labels.await_args_list:
        assert "human-required" not in call.args[1]


@pytest.mark.asyncio
async def test_widened_terminal_returns_issue_to_hitl_queue(tmp_path: Path) -> None:
    loop, state, pr, _audit = _make_loop(
        tmp_path,
        label_map={"hydraflow-hitl": [_issue(5, ["hydraflow-hitl"])]},
    )
    state.get_hitl_origin = MagicMock(return_value="hydraflow-ready")
    _stub_spawn(loop, _NEEDS_HUMAN_OUTPUT)

    await loop._do_work()

    pr.swap_pipeline_labels.assert_any_await(5, "hydraflow-hitl")
    pr.add_labels.assert_any_await(5, ["human-required"])
    state.reset_issue_attempts.assert_not_called()


@pytest.mark.asyncio
async def test_widened_exhausted_precheck_returns_claim_to_queue(
    tmp_path: Path,
) -> None:
    """An autofix-claimed issue whose attempt budget is already spent must be
    returned to the human queue, not left orphaned outside both queues."""
    loop, state, pr, _audit = _make_loop(
        tmp_path,
        label_map={"hydraflow-hitl-autofix": [_issue(6, ["hydraflow-hitl-autofix"])]},
    )
    state.get_auto_agent_attempts = MagicMock(return_value=3)

    result = await loop._do_work()

    assert result["result_status"] == "skipped_exhausted"
    pr.swap_pipeline_labels.assert_awaited_once_with(6, "hydraflow-hitl")
    pr.add_labels.assert_awaited_with(6, ["human-required", "auto-agent-exhausted"])


@pytest.mark.asyncio
async def test_widened_deny_list_defers_to_human(tmp_path: Path) -> None:
    loop, _state, pr, _audit = _make_loop(
        tmp_path,
        label_map={
            "hydraflow-hitl": [_issue(5, ["hydraflow-hitl", "principles-stuck"])]
        },
    )
    result = await loop._do_work()
    assert result["result_status"] == "skipped_deny_list"
    pr.add_labels.assert_awaited_with(5, ["human-required"])


# ---------------------------------------------------------------------------
# Origin → playbook routing
# ---------------------------------------------------------------------------


def test_playbook_stem_for_origin_mapping(tmp_path: Path) -> None:
    loop, _state, _pr, _audit = _make_loop(tmp_path)
    assert loop._playbook_stem_for_origin("hydraflow-ready") == (
        "implement-cap-exhausted"
    )
    assert loop._playbook_stem_for_origin("hydraflow-plan") == "plan-stuck"
    assert loop._playbook_stem_for_origin("hydraflow-review") == "review-stuck"
    assert loop._playbook_stem_for_origin("operator-abort") == "_default"
    assert loop._playbook_stem_for_origin(None) == "_default"
    assert loop._playbook_stem_for_origin("") == "_default"


@pytest.mark.asyncio
async def test_widened_implement_origin_renders_cap_exhausted_playbook(
    tmp_path: Path,
) -> None:
    loop, state, _pr, _audit = _make_loop(
        tmp_path,
        label_map={"hydraflow-hitl": [_issue(5, ["hydraflow-hitl"])]},
    )
    state.get_hitl_origin = MagicMock(return_value="hydraflow-ready")
    captured = _stub_spawn(loop, _RESOLVED_OUTPUT)

    await loop._do_work()

    assert "Do NOT repeat the failed implementation shape" in captured["prompt"]


# ---------------------------------------------------------------------------
# Close reconciliation for widened labels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_clears_attempts_for_closed_widened_issues(
    tmp_path: Path,
) -> None:
    loop, state, pr, _audit = _make_loop(tmp_path)
    state.get_auto_agent_attempts = MagicMock(return_value=2)

    async def _closed(label: str, limit: int = 200) -> list[dict]:
        if label == "hydraflow-hitl-autofix":
            return [{"number": 11}]
        if label == "hydraflow-hitl":
            return [{"number": 11}, {"number": 12}]
        return []

    pr.list_closed_issues_by_label = AsyncMock(side_effect=_closed)
    cleared = await loop._reconcile_closed_issues()
    assert cleared == 2
    state.clear_auto_agent_attempts.assert_any_call(11)
    state.clear_auto_agent_attempts.assert_any_call(12)


@pytest.mark.asyncio
async def test_reconcile_flag_off_polls_escalation_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYDRAFLOW_AUTO_AGENT_HITL_INTAKE_ENABLED", "false")
    loop, _state, pr, _audit = _make_loop(tmp_path)
    await loop._reconcile_closed_issues()
    polled = [c.args[0] for c in pr.list_closed_issues_by_label.await_args_list]
    assert polled == ["hitl-escalation"]
