"""Integration test — AGENT_ACTIVITY events are emitted alongside TRANSCRIPT_LINE."""

from __future__ import annotations

import json

import pytest

from events import EventBus, EventType, HydraFlowEvent


@pytest.mark.asyncio
async def test_activity_event_emitted_for_tool_use(tmp_path):
    """stream_claude_process emits AGENT_ACTIVITY for Claude tool_use lines."""
    from unittest.mock import AsyncMock

    from runner_utils import stream_claude_process

    tool_use_line = json.dumps(
        {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool_1",
                        "name": "Read",
                        "input": {"file_path": "src/config.py"},
                    },
                ],
            },
        }
    )

    async def fake_create_process(cmd, **_kwargs):
        proc = AsyncMock()
        proc.pid = 12345
        proc.returncode = 0

        async def _stdout():
            yield (tool_use_line + "\n").encode()

        proc.stdout = _stdout()
        proc.stderr = AsyncMock()
        proc.stderr.read = AsyncMock(return_value=b"")
        proc.stdin = None
        proc.wait = AsyncMock(return_value=0)
        proc.kill = AsyncMock()
        return proc

    bus = EventBus()
    collected: list[HydraFlowEvent] = []
    _original_publish = bus.publish

    async def _capture(event: HydraFlowEvent) -> None:
        collected.append(event)
        await _original_publish(event)

    bus.publish = _capture  # type: ignore[assignment]

    runner_mock = AsyncMock()
    runner_mock.create_streaming_process = fake_create_process

    await stream_claude_process(
        cmd=["claude", "-p", "--output-format", "stream-json"],
        prompt="test prompt",
        cwd=tmp_path,
        active_procs=set(),
        event_bus=bus,
        event_data={"issue": 42, "source": "implementer"},
        logger=__import__("logging").getLogger("test"),
        runner=runner_mock,
    )

    activity_events = [e for e in collected if e.type == EventType.AGENT_ACTIVITY]
    transcript_events = [e for e in collected if e.type == EventType.TRANSCRIPT_LINE]

    # Both event types should be emitted
    assert len(activity_events) >= 1, (
        f"Expected AGENT_ACTIVITY events, got {len(activity_events)}"
    )
    assert activity_events[0].data["activity_type"] == "tool_call"
    assert activity_events[0].data["tool_name"] == "Read"
    assert activity_events[0].data["issue"] == 42
    assert activity_events[0].data["source"] == "implementer"

    # Transcript line still emitted (unchanged behavior)
    assert len(transcript_events) >= 1, (
        f"Expected TRANSCRIPT_LINE events, got {len(transcript_events)}"
    )


@pytest.mark.asyncio
async def test_no_activity_event_for_session_lines(tmp_path):
    """Non-interesting lines (session, meta) should not emit AGENT_ACTIVITY."""
    from unittest.mock import AsyncMock

    from runner_utils import stream_claude_process

    session_line = json.dumps({"type": "session", "session_id": "abc-123"})

    async def fake_create_process(cmd, **_kwargs):
        proc = AsyncMock()
        proc.pid = 12345
        proc.returncode = 0

        async def _stdout():
            yield (session_line + "\n").encode()

        proc.stdout = _stdout()
        proc.stderr = AsyncMock()
        proc.stderr.read = AsyncMock(return_value=b"")
        proc.stdin = None
        proc.wait = AsyncMock(return_value=0)
        proc.kill = AsyncMock()
        return proc

    bus = EventBus()
    collected: list[HydraFlowEvent] = []
    _original_publish = bus.publish

    async def _capture(event: HydraFlowEvent) -> None:
        collected.append(event)
        await _original_publish(event)

    bus.publish = _capture  # type: ignore[assignment]

    runner_mock = AsyncMock()
    runner_mock.create_streaming_process = fake_create_process

    await stream_claude_process(
        cmd=["claude", "-p", "--output-format", "stream-json"],
        prompt="test prompt",
        cwd=tmp_path,
        active_procs=set(),
        event_bus=bus,
        event_data={"issue": 99, "source": "planner"},
        logger=__import__("logging").getLogger("test"),
        runner=runner_mock,
    )

    activity_events = [e for e in collected if e.type == EventType.AGENT_ACTIVITY]
    assert len(activity_events) == 0, (
        f"Expected no AGENT_ACTIVITY for session line, got {len(activity_events)}"
    )
