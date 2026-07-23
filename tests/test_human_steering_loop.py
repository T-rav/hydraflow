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


@pytest.mark.asyncio
async def test_loop_abort_is_sticky_across_reticks():
    # Tick 1: a fresh, authorized /abort comment (past the OLD high-water-mark)
    # is seen -> flow="abort" is persisted and the mark advances past it.
    # Tick 2: same comment history, no new comments -> parse_directives no
    # longer reports the (now-stale) abort, but the persisted flow must NOT
    # be clobbered back to "running". Abort is a sticky terminal flow;
    # only the actuator (park) or a fresh directive changes it thereafter.
    from human_steering_loop import HumanSteeringLoop

    comments = [
        {
            "user": {"login": "a"},
            "body": "/abort",
            "created_at": "2026-07-03T10:00:00Z",
        },
    ]
    prs = MagicMock()
    prs.list_issue_comments = AsyncMock(return_value=comments)

    persisted: dict[str, SteeringState] = {"42": SteeringState()}
    state = MagicMock()
    state.get_human_steering.side_effect = lambda key: persisted[key]

    def _set(key: str, value: SteeringState) -> None:
        persisted[key] = value

    state.set_human_steering.side_effect = _set

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
    assert persisted["42"].flow == "abort"

    # Re-tick with the identical comment history: the high-water-mark
    # advanced on tick 1, so parse_directives will no longer see the abort
    # as fresh and would recompute "running" absent the stickiness fix.
    await loop._do_work()
    assert persisted["42"].flow == "abort"


@pytest.mark.asyncio
async def test_loop_pause_stays_resumable_not_sticky():
    # Pause must remain a live declarative recompute each tick: once the
    # pause condition lifts (no active /pause newer than the last /resume),
    # flow should resolve back to "running" on the very next tick, unlike
    # abort which stays sticky once persisted.
    from human_steering_loop import HumanSteeringLoop

    persisted: dict[str, SteeringState] = {"42": SteeringState(flow="paused")}
    state = MagicMock()
    state.get_human_steering.side_effect = lambda key: persisted[key]

    def _set(key: str, value: SteeringState) -> None:
        persisted[key] = value

    state.set_human_steering.side_effect = _set

    prs = MagicMock()
    # No pause/resume comments at all this tick -> parse_directives
    # recomputes the default flow, "running".
    prs.list_issue_comments = AsyncMock(return_value=[])

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
    assert persisted["42"].flow == "running"
