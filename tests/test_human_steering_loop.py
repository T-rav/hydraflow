from unittest.mock import AsyncMock, MagicMock

import pytest

from models import SteeringState


@pytest.mark.asyncio
async def test_loop_writes_steering_state_for_active_issue():
    from human_steering_loop import HumanSteeringLoop

    prs = MagicMock()
    prs.list_issue_comments = AsyncMock(
        return_value=[
            {
                "user": {"login": "a"},
                "body": "/steer focus tests",
                "created_at": "2026-07-03T10:00:00Z",
            },
            {
                "user": {"login": "a"},
                "body": "/pause",
                "created_at": "2026-07-03T10:01:00Z",
            },
        ]
    )
    state = MagicMock()
    state.get_human_steering.return_value = SteeringState()
    config = MagicMock(
        human_steering_enabled=True,
        human_steering_interval_seconds=60,
        human_steering_authorized_users=["a"],
    )
    deps = MagicMock()
    loop = HumanSteeringLoop(
        config=config, state=state, prs=prs, deps=deps, active_issues_cb=lambda: [42]
    )
    loop._enabled_cb = lambda name: True  # kill-switch open
    result = await loop._do_work()
    # wrote a paused, guided state for issue "42"
    args = state.set_human_steering.call_args
    assert args.args[0] == "42"
    written = args.args[1]
    assert written.flow == "paused" and written.guidance == "focus tests"
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_loop_disabled_by_config_is_noop():
    from human_steering_loop import HumanSteeringLoop

    config = MagicMock(human_steering_enabled=False)
    loop = HumanSteeringLoop(
        config=config,
        state=MagicMock(),
        prs=MagicMock(),
        deps=MagicMock(),
        active_issues_cb=lambda: [1],
    )
    loop._enabled_cb = lambda name: True
    assert (await loop._do_work())["status"] == "config_disabled"


@pytest.mark.asyncio
async def test_loop_preserves_unconsumed_redo_on_retick():
    # /redo already applied last tick (mark advanced past it) and the actuator
    # hasn't consumed prev.redo_phase yet — a re-tick must NOT clobber it.
    from human_steering_loop import HumanSteeringLoop

    prs = MagicMock()
    prs.list_issue_comments = AsyncMock(
        return_value=[
            {
                "user": {"login": "a"},
                "body": "/redo shape",
                "created_at": "2026-07-03T10:00:00Z",
            },
        ]
    )
    state = MagicMock()
    state.get_human_steering.return_value = SteeringState(
        redo_phase="shape", redo_count=0, last_applied_ts="2026-07-03T10:00:00Z"
    )
    config = MagicMock(
        human_steering_enabled=True,
        human_steering_interval_seconds=60,
        human_steering_authorized_users=["a"],
    )
    loop = HumanSteeringLoop(
        config=config,
        state=state,
        prs=prs,
        deps=MagicMock(),
        active_issues_cb=lambda: [42],
    )
    loop._enabled_cb = lambda name: True
    await loop._do_work()
    assert state.set_human_steering.call_args.args[1].redo_phase == "shape"
