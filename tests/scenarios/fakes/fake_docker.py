"""FakeDocker — emulates the agent-cli container streaming protocol.

Scripted event sequences drive `run_agent`. Fault modes inject single-shot
failures (timeout, OOM, malformed stream, non-zero exit) for scenario tests.
"""

from __future__ import annotations

from collections import deque
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

FaultKind = Literal["timeout", "oom", "exit_nonzero", "malformed_stream"]


@dataclass
class _Invocation:
    command: list[str]
    mounts: dict[str, Path] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 3600.0


class FakeDocker:
    """Scripted agent-cli container runner."""

    def __init__(self) -> None:
        self._scripts: deque[list[dict[str, Any]]] = deque()
        self._next_fault: FaultKind | None = None
        self.invocations: list[_Invocation] = []

    def script_run(self, events: list[dict[str, Any]]) -> None:
        """Queue the events that the NEXT run_agent call will yield."""
        self._scripts.append(list(events))

    def fail_next(self, *, kind: FaultKind) -> None:
        """Inject a single-shot fault into the next run_agent call."""
        self._next_fault = kind

    async def run_agent(
        self,
        *,
        command: list[str],
        mounts: Mapping[str, Path] | None = None,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float = 3600.0,
    ) -> AsyncIterator[dict[str, Any]]:
        self.invocations.append(
            _Invocation(
                command=list(command),
                mounts=dict(mounts) if mounts else {},
                env=dict(env) if env else {},
                timeout_seconds=timeout_seconds,
            )
        )

        fault = self._next_fault
        self._next_fault = None

        if fault == "timeout":
            return _timeout_iter()
        if fault == "oom":
            return _aiter([{"type": "result", "success": False, "exit_code": 137}])
        if fault == "exit_nonzero":
            return _aiter([{"type": "result", "success": False, "exit_code": 1}])
        if fault == "malformed_stream":
            return _aiter(
                [
                    {"type": "garbage", "junk": "not-valid-agent-cli"},
                    {"type": "result", "success": False, "exit_code": 1},
                ]
            )

        if self._scripts:
            events = self._scripts.popleft()
        else:
            events = [{"type": "result", "success": True, "exit_code": 0}]
        return _aiter(events)


async def _aiter(events: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
    for event in events:
        yield event


async def _timeout_iter() -> AsyncIterator[dict[str, Any]]:
    raise TimeoutError("FakeDocker: timeout fault injected")
    yield  # pragma: no cover — unreachable, makes function an async generator
