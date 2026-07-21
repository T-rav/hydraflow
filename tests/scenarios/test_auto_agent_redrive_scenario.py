"""MockWorld scenario for #9719 — escalation TTL re-drive.

Real ``StateTracker`` + ``FakeGitHub`` (no subprocess/git/network): a stuck
``hitl-escalation`` issue that exhausted auto-agent attempts and carried
``human-required`` past the TTL is re-fed to preflight — labels removed,
attempts cleared, marker disarmed — and re-enters the eligible pool. The
sandbox tier cannot advance wall-clock days (no state-marker seed
materializer yet), so per the "sandbox can't assert timing → MockWorld owns
timing" precedent this scenario is the loop-integration gate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from auto_agent_preflight_loop import AutoAgentPreflightLoop
from mockworld.fakes.fake_github import FakeGitHub
from preflight.agent import PreflightSpawn
from state import StateTracker
from tests.helpers import make_bg_loop_deps

ISSUE = 9618
STUCK_LABELS = [
    "hitl-escalation",
    "human-required",
    "auto-agent-exhausted",
    "flaky-test-stuck",
]


def _iso_days_ago(days: float) -> str:
    ts = datetime.now(UTC) - timedelta(days=days)
    return ts.isoformat().replace("+00:00", "Z")


def _make_world(tmp_path: Path):
    deps = make_bg_loop_deps(tmp_path, enabled=True)
    state = StateTracker(state_file=tmp_path / "state.json")
    gh = FakeGitHub()
    audit = MagicMock()
    audit.append = MagicMock()
    audit.entries_for_issue = MagicMock(return_value=[])
    audit.daily_spend = MagicMock(return_value=0.0)
    loop = AutoAgentPreflightLoop(
        config=deps.config,
        state=state,
        pr_manager=gh,
        wiki_store=None,
        audit_store=audit,
        deps=deps.loop_deps,
    )

    async def _spawn(prompt: str, worktree_path: str) -> PreflightSpawn:
        return PreflightSpawn(
            process=None,
            output_text=(
                "<status>needs_human</status><confidence>low</confidence>"
                "<blocked_reason>insufficient_context</blocked_reason>"
                "<diagnosis>fresh attempt</diagnosis>"
            ),
            cost_usd=0.5,
            tokens=50,
            crashed=False,
        )

    loop._build_spawn_fn = lambda issue: _spawn
    return loop, state, gh


def _seed_stuck_escalation(state, gh, *, extra_labels=(), exhausted_days_ago=10.0):
    gh.add_issue(
        ISSUE, "stuck escalation", "gap is real", STUCK_LABELS + list(extra_labels)
    )
    for _ in range(3):
        state.bump_auto_agent_attempts(ISSUE)
    state.arm_auto_agent_redrive(ISSUE, _iso_days_ago(exhausted_days_ago))


@pytest.mark.asyncio
async def test_aged_stuck_escalation_is_redriven_and_reenters_pool(
    tmp_path: Path,
) -> None:
    loop, state, gh = _make_world(tmp_path)
    _seed_stuck_escalation(state, gh)

    result = await loop._do_work()
    assert result is not None
    assert result["status"] == "ok"

    labels = gh._issues[ISSUE].labels
    assert "human-required" not in labels
    assert "auto-agent-exhausted" not in labels
    assert "hitl-escalation" in labels
    # Marker disarmed, count persisted, attempt budget reset (the re-driven
    # attempt in this same tick consumes attempt 1 of the fresh budget).
    assert state.get_auto_agent_redrive_count(ISSUE) == 1
    assert state.list_armed_auto_agent_redrives() == []
    assert state.get_auto_agent_attempts(ISSUE) <= 1
    # The re-drive comment is the next attempt's diverse-retry directive.
    assert any("re-drive" in str(c).lower() for c in gh._issues[ISSUE].comments)
    # The issue is back in the eligible pool (no human-required filter hit).
    eligible = await loop._poll_eligible_issues()
    assert [i["number"] for i in eligible] == [ISSUE]


@pytest.mark.asyncio
async def test_hitl_active_claim_is_respected(tmp_path: Path) -> None:
    loop, state, gh = _make_world(tmp_path)
    _seed_stuck_escalation(state, gh, extra_labels=["hydraflow-hitl-active"])

    await loop._do_work()

    labels = gh._issues[ISSUE].labels
    assert "human-required" in labels
    assert "auto-agent-exhausted" in labels
    armed = state.list_armed_auto_agent_redrives()
    assert [(i, c) for i, _ts, c in armed] == [(ISSUE, 0)]
    assert state.get_auto_agent_redrive_count(ISSUE) == 0


@pytest.mark.asyncio
async def test_capped_marker_stays_human_required(tmp_path: Path) -> None:
    # A re-driven escalation that exhausted again past the cap must not
    # loop forever: it stays parked at human-required.
    loop, state, gh = _make_world(tmp_path)
    _seed_stuck_escalation(state, gh, exhausted_days_ago=60.0)
    state.record_auto_agent_redrive(ISSUE)  # count -> 1 (== default cap)
    state.arm_auto_agent_redrive(ISSUE, _iso_days_ago(60))  # re-exhausted

    await loop._do_work()

    labels = gh._issues[ISSUE].labels
    assert "human-required" in labels
    assert "auto-agent-exhausted" in labels
    assert state.get_auto_agent_redrive_count(ISSUE) == 1
