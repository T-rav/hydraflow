"""Regression tests for #9719 — AutoAgentPreflightLoop TTL re-drive.

Loop-level coverage: arming at the exhaustion transitions, the re-drive
gate matrix (aged / not-aged / claimed-label / claimed-comment / capped /
disabled / resolved-not-closed), state-first ordering, close-reconcile,
and the audit-log-survives-re-drive invariant (the diverse-retry source:
``gather_context`` reads ``prior_attempts`` from the durable JSONL, which
a re-drive must never clear).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from auto_agent_preflight_loop import AutoAgentPreflightLoop  # noqa: E402
from preflight.agent import PreflightSpawn  # noqa: E402
from preflight.audit import PreflightAuditEntry, PreflightAuditStore  # noqa: E402
from state import StateTracker  # noqa: E402
from tests.helpers import make_bg_loop_deps  # noqa: E402


def _iso_days_ago(days: float) -> str:
    ts = datetime.now(UTC) - timedelta(days=days)
    return ts.isoformat().replace("+00:00", "Z")


def _make_loop(tmp_path: Path, **config_updates):
    base = make_bg_loop_deps(tmp_path, enabled=True)
    config = (
        base.config.model_copy(update=config_updates) if config_updates else base.config
    )
    state = StateTracker(state_file=tmp_path / "state.json")
    pr = AsyncMock()
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    pr.list_issues_by_label = AsyncMock(return_value=[])
    pr.list_issue_comments = AsyncMock(return_value=[])
    audit = MagicMock()
    audit.append = MagicMock()
    audit.entries_for_issue = MagicMock(return_value=[])
    audit.daily_spend = MagicMock(return_value=0.0)
    loop = AutoAgentPreflightLoop(
        config=config,
        state=state,
        pr_manager=pr,
        wiki_store=None,
        audit_store=audit,
        deps=base.loop_deps,
    )
    return loop, state, pr, audit


def _label_polls(pr: AsyncMock, mapping: dict[str, list[int]]) -> None:
    """Route ``list_issues_by_label`` per label — numbers only, mirroring the
    real projection (candidate discovery must never read a summary's labels)."""

    async def _poll(label: str):
        return [
            {"number": n, "title": "t", "body": "b"} for n in mapping.get(label, [])
        ]

    pr.list_issues_by_label = AsyncMock(side_effect=_poll)


def _stub_spawn(loop: AutoAgentPreflightLoop, output: str, *, cost: float = 1.0):
    async def _spawn(prompt: str, worktree_path: str) -> PreflightSpawn:
        return PreflightSpawn(
            process=None,
            output_text=output,
            cost_usd=cost,
            tokens=100,
            crashed=False,
        )

    loop._build_spawn_fn = lambda issue: _spawn


_ESCALATION_ISSUE = {
    "number": 9618,
    "body": "still broken",
    "labels": [{"name": "hitl-escalation"}, {"name": "flaky-test-stuck"}],
}


# ---------------------------------------------------------------------------
# Arming at the exhaustion transitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attempt_cap_branch_arms_marker_idempotently(tmp_path: Path) -> None:
    loop, state, _pr, _audit = _make_loop(tmp_path)
    for _ in range(3):
        state.bump_auto_agent_attempts(9618)

    result = await loop._process_one(dict(_ESCALATION_ISSUE))
    assert result["status"] == "skipped_exhausted"
    armed = state.list_armed_auto_agent_redrives()
    assert len(armed) == 1
    issue, first_ts, count = armed[0]
    assert (issue, count) == (9618, 0)

    # A later re-confirmation tick re-runs the same branch: the marker's
    # clock must NOT be refreshed (the #9716 re-arm trap).
    await loop._process_one(dict(_ESCALATION_ISSUE))
    assert state.list_armed_auto_agent_redrives() == [(9618, first_ts, 0)]


@pytest.mark.asyncio
async def test_exhausting_attempt_via_apply_decision_arms_marker(
    tmp_path: Path,
) -> None:
    loop, state, _pr, _audit = _make_loop(tmp_path)
    state.bump_auto_agent_attempts(9618)
    state.bump_auto_agent_attempts(9618)  # attempt 3 (the cap) runs below
    _stub_spawn(
        loop,
        "<status>needs_human</status><confidence>low</confidence>"
        "<blocked_reason>insufficient_context</blocked_reason>"
        "<diagnosis>still stuck</diagnosis>",
    )

    await loop._process_one(dict(_ESCALATION_ISSUE))

    armed = state.list_armed_auto_agent_redrives()
    assert [(i, c) for i, _ts, c in armed] == [(9618, 0)]


@pytest.mark.asyncio
async def test_resolved_attempt_does_not_arm_marker(tmp_path: Path) -> None:
    loop, state, _pr, _audit = _make_loop(tmp_path)
    _stub_spawn(
        loop,
        "<status>resolved</status><pr_url>https://x/pr/1</pr_url>"
        "<diagnosis>fixed</diagnosis>",
    )

    await loop._process_one(dict(_ESCALATION_ISSUE))

    assert state.list_armed_auto_agent_redrives() == []


# ---------------------------------------------------------------------------
# Re-drive gate matrix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aged_unclaimed_marker_is_redriven(tmp_path: Path) -> None:
    loop, state, pr, audit = _make_loop(tmp_path)
    state.bump_auto_agent_attempts(9618)
    state.bump_auto_agent_attempts(9618)
    state.arm_auto_agent_redrive(9618, _iso_days_ago(10))
    _label_polls(pr, {"human-required": [9618]})

    redriven = await loop._redrive_stuck_escalations()

    assert redriven == 1
    pr.remove_label.assert_any_await(9618, "human-required")
    pr.remove_label.assert_any_await(9618, "auto-agent-exhausted")
    pr.post_comment.assert_awaited_once()
    comment = pr.post_comment.await_args.args[1]
    assert "re-drive" in comment.lower()
    assert state.get_auto_agent_attempts(9618) == 0
    assert state.get_auto_agent_redrive_count(9618) == 1
    assert state.list_armed_auto_agent_redrives() == []
    # An audit event records the re-drive (status="redrive", zero cost).
    entry = audit.append.call_args.args[0]
    assert entry.status == "redrive"
    assert entry.cost_usd == 0.0


@pytest.mark.asyncio
async def test_marker_below_ttl_is_not_redriven(tmp_path: Path) -> None:
    loop, state, pr, _audit = _make_loop(tmp_path)
    ts = _iso_days_ago(2)  # below the 5-day default TTL
    state.arm_auto_agent_redrive(9618, ts)
    _label_polls(pr, {"human-required": [9618]})

    assert await loop._redrive_stuck_escalations() == 0
    pr.remove_label.assert_not_awaited()
    assert state.list_armed_auto_agent_redrives() == [(9618, ts, 0)]


@pytest.mark.asyncio
async def test_hitl_active_label_blocks_redrive(tmp_path: Path) -> None:
    loop, state, pr, _audit = _make_loop(tmp_path)
    state.arm_auto_agent_redrive(9618, _iso_days_ago(10))
    _label_polls(
        pr,
        {"human-required": [9618], "hydraflow-hitl-active": [9618]},
    )

    assert await loop._redrive_stuck_escalations() == 0
    pr.remove_label.assert_not_awaited()
    assert state.get_auto_agent_redrive_count(9618) == 0


@pytest.mark.asyncio
async def test_recent_authorized_human_comment_blocks_redrive(
    tmp_path: Path,
) -> None:
    loop, state, pr, _audit = _make_loop(
        tmp_path, human_steering_authorized_users=["travis"]
    )
    state.arm_auto_agent_redrive(9618, _iso_days_ago(10))
    _label_polls(pr, {"human-required": [9618]})
    pr.list_issue_comments = AsyncMock(
        return_value=[
            {
                "user": {"login": "travis"},
                "body": "looking at this",
                "created_at": _iso_days_ago(1),  # inside the 2-day quiet window
            }
        ]
    )

    assert await loop._redrive_stuck_escalations() == 0
    pr.remove_label.assert_not_awaited()


@pytest.mark.asyncio
async def test_recent_bot_comment_does_not_block_redrive(tmp_path: Path) -> None:
    # The loop posts "Auto-Agent attempt N…" comments itself; only
    # allowlisted humans count as claim activity.
    loop, state, pr, _audit = _make_loop(
        tmp_path, human_steering_authorized_users=["travis"]
    )
    state.arm_auto_agent_redrive(9618, _iso_days_ago(10))
    _label_polls(pr, {"human-required": [9618]})
    pr.list_issue_comments = AsyncMock(
        return_value=[
            {
                "user": {"login": "hydraflow-bot"},
                "body": "**Auto-Agent attempt 3**",
                "created_at": _iso_days_ago(0.5),
            }
        ]
    )

    assert await loop._redrive_stuck_escalations() == 1


@pytest.mark.asyncio
async def test_comment_poll_failure_blocks_redrive_fail_safe(
    tmp_path: Path,
) -> None:
    # Never yank an issue we can't inspect.
    loop, state, pr, _audit = _make_loop(
        tmp_path, human_steering_authorized_users=["travis"]
    )
    state.arm_auto_agent_redrive(9618, _iso_days_ago(10))
    _label_polls(pr, {"human-required": [9618]})
    pr.list_issue_comments = AsyncMock(side_effect=RuntimeError("gh down"))

    assert await loop._redrive_stuck_escalations() == 0
    pr.remove_label.assert_not_awaited()


@pytest.mark.asyncio
async def test_redrive_count_at_cap_is_not_redriven(tmp_path: Path) -> None:
    loop, state, pr, _audit = _make_loop(tmp_path)  # max_attempts default 1
    state.arm_auto_agent_redrive(9618, _iso_days_ago(60))
    state.record_auto_agent_redrive(9618)  # count -> 1 (== cap)
    state.arm_auto_agent_redrive(9618, _iso_days_ago(60))  # re-exhausted
    _label_polls(pr, {"human-required": [9618]})

    assert await loop._redrive_stuck_escalations() == 0
    pr.remove_label.assert_not_awaited()
    assert state.get_auto_agent_redrive_count(9618) == 1


@pytest.mark.asyncio
async def test_backoff_extends_ttl_for_second_redrive(tmp_path: Path) -> None:
    # With max=2: re-drive k needs ttl_days * multiplier**k → 5d then 15d.
    loop, state, pr, _audit = _make_loop(tmp_path, auto_agent_redrive_max_attempts=2)
    state.record_auto_agent_redrive(9618)  # first re-drive already happened
    state.arm_auto_agent_redrive(9618, _iso_days_ago(10))  # re-exhausted 10d ago
    _label_polls(pr, {"human-required": [9618]})

    assert await loop._redrive_stuck_escalations() == 0  # 10d < 15d backoff TTL

    state.clear_auto_agent_redrive(9618)
    state.record_auto_agent_redrive(9618)
    state.arm_auto_agent_redrive(9618, _iso_days_ago(20))  # 20d > 15d

    assert await loop._redrive_stuck_escalations() == 1


@pytest.mark.asyncio
async def test_disabled_config_skips_scan_entirely(tmp_path: Path) -> None:
    loop, state, pr, _audit = _make_loop(tmp_path, auto_agent_redrive_enabled=False)
    state.arm_auto_agent_redrive(9618, _iso_days_ago(10))

    assert await loop._redrive_stuck_escalations() == 0
    pr.list_issues_by_label.assert_not_awaited()


@pytest.mark.asyncio
async def test_marker_absent_from_human_required_poll_is_cleared(
    tmp_path: Path,
) -> None:
    # Resolved-but-not-closed: the label is already gone → drop the stale
    # marker instead of re-driving.
    loop, state, pr, _audit = _make_loop(tmp_path)
    state.arm_auto_agent_redrive(9618, _iso_days_ago(10))
    _label_polls(pr, {"human-required": []})

    assert await loop._redrive_stuck_escalations() == 0
    pr.remove_label.assert_not_awaited()
    assert state.list_armed_auto_agent_redrives() == []
    assert state.get_auto_agent_redrive_count(9618) == 0


@pytest.mark.asyncio
async def test_malformed_exhausted_at_never_redrives(tmp_path: Path) -> None:
    loop, state, pr, _audit = _make_loop(tmp_path)
    state.arm_auto_agent_redrive(9618, "not-a-timestamp")
    _label_polls(pr, {"human-required": [9618]})

    assert await loop._redrive_stuck_escalations() == 0
    pr.remove_label.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_failure_aborts_scan_without_state_changes(
    tmp_path: Path,
) -> None:
    loop, state, pr, _audit = _make_loop(tmp_path)
    ts = _iso_days_ago(10)
    state.arm_auto_agent_redrive(9618, ts)
    pr.list_issues_by_label = AsyncMock(side_effect=RuntimeError("gh down"))

    assert await loop._redrive_stuck_escalations() == 0
    assert state.list_armed_auto_agent_redrives() == [(9618, ts, 0)]


# ---------------------------------------------------------------------------
# Audit-log survival (the diverse-retry source) + budget + reconcile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redrive_preserves_prior_attempt_audit_entries(
    tmp_path: Path,
) -> None:
    loop, state, pr, _audit = _make_loop(tmp_path)
    real_audit = PreflightAuditStore(tmp_path)
    loop._audit_store = real_audit
    for n in (1, 2):
        real_audit.append(
            PreflightAuditEntry(
                ts=_iso_days_ago(12),
                issue=9618,
                sub_label="flaky-test-stuck",
                attempt_n=n,
                prompt_hash="h",
                cost_usd=1.0,
                wall_clock_s=10.0,
                tokens=100,
                status="retry",
                pr_url=None,
                diagnosis=f"original failure {n}",
                llm_summary=f"original failure {n}",
            )
        )
    state.arm_auto_agent_redrive(9618, _iso_days_ago(10))
    _label_polls(pr, {"human-required": [9618]})

    assert await loop._redrive_stuck_escalations() == 1

    entries = real_audit.entries_for_issue(9618)
    diagnoses = [e.diagnosis for e in entries]
    assert "original failure 1" in diagnoses
    assert "original failure 2" in diagnoses
    assert entries[-1].status == "redrive"


@pytest.mark.asyncio
async def test_budget_gate_short_circuits_before_redrive_scan(
    tmp_path: Path,
) -> None:
    loop, state, pr, audit = _make_loop(tmp_path, auto_agent_daily_budget_usd=1.0)
    audit.daily_spend = MagicMock(return_value=5.0)
    ts = _iso_days_ago(10)
    state.arm_auto_agent_redrive(9618, ts)

    result = await loop._do_work()

    assert result is not None
    assert result["status"] == "budget_exceeded"
    pr.list_issues_by_label.assert_not_awaited()
    assert state.list_armed_auto_agent_redrives() == [(9618, ts, 0)]


@pytest.mark.asyncio
async def test_closed_issue_clears_redrive_marker(tmp_path: Path) -> None:
    loop, state, pr, _audit = _make_loop(tmp_path)
    state.arm_auto_agent_redrive(9618, _iso_days_ago(10))
    state.record_auto_agent_redrive(7000)
    pr.list_closed_issues_by_label = AsyncMock(
        return_value=[{"number": 9618}, {"number": 7000}]
    )

    await loop._reconcile_closed_issues()

    assert state.list_armed_auto_agent_redrives() == []
    assert state.get_auto_agent_redrive_count(9618) == 0
    assert state.get_auto_agent_redrive_count(7000) == 0
