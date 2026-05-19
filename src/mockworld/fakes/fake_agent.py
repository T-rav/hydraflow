"""FakeAgent — satisfies AgentPort for scenario testing (ADR-0047).

Provides deterministic, in-memory control over agent subprocess behaviour
without spawning any real processes.  Designed for:

- ``merge_conflict_resolver`` scenarios that inject an ``AgentPort``
- Any future infrastructure module that depends on ``AgentPort``

Seeding API
-----------
``script_execute(results)``
    Queue transcript strings to return from ``execute()`` calls in order.
    When the queue drains the last transcript is repeated (sticky-tail
    semantics matching ``_ScriptedRunner._pop``).

``script_verify(results)``
    Queue ``LoopResult`` objects returned by ``verify_result()`` calls.

``script_build_command(cmd)``
    Override the command returned by ``build_command()``.  Defaults to
    ``["fake-agent"]``.

Observation API
---------------
``execute_calls``
    List of ``(cmd, prompt, cwd, event_data)`` tuples recorded each time
    ``execute()`` was called.

``verify_calls``
    List of ``(worktree_path, branch)`` tuples recorded by
    ``verify_result()``.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

from models import LoopResult

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from models import TranscriptEventData


_DEFAULT_TRANSCRIPT = "<FakeAgent: no transcript scripted>"
_DEFAULT_COMMAND = ["fake-agent"]


class FakeAgent:
    """Deterministic in-memory implementation of ``AgentPort``.

    Satisfies ``ports.AgentPort`` via structural subtyping — every public
    method matches the port signature exactly so
    ``isinstance(FakeAgent(), AgentPort)`` returns True.
    """

    _is_fake_adapter = True  # read by dashboard for MOCKWORLD banner

    def __init__(self) -> None:
        self._exec_queue: deque[str] = deque()
        self._exec_last: str | None = None
        self._verify_queue: deque[LoopResult] = deque()
        self._verify_last: LoopResult | None = None
        self._command: list[str] = list(_DEFAULT_COMMAND)
        # Observation lists — assertions in scenario tests
        self.execute_calls: list[tuple[list[str], str, Path, Any]] = []
        self.verify_calls: list[tuple[Path, str]] = []

    # ------------------------------------------------------------------
    # Seeding / scripting API
    # ------------------------------------------------------------------

    def script_execute(self, results: list[str]) -> None:
        """Queue transcript strings returned by successive ``execute()`` calls.

        When the queue drains, the last value is repeated.
        """
        self._exec_queue = deque(results)
        self._exec_last = None

    def script_verify(self, results: list[LoopResult]) -> None:
        """Queue ``LoopResult`` objects returned by successive ``verify_result()`` calls.

        When the queue drains, the last value is repeated (defaults to
        ``LoopResult(passed=True, summary="OK")`` if never scripted).
        """
        self._verify_queue = deque(results)
        self._verify_last = None

    def script_build_command(self, cmd: list[str]) -> None:
        """Override the list returned by ``build_command()``."""
        self._command = list(cmd)

    # ------------------------------------------------------------------
    # AgentPort interface
    # ------------------------------------------------------------------

    def build_command(self, _worktree_path: Path | None = None) -> list[str]:
        """Return the scripted command (default: ``["fake-agent"]``)."""
        return list(self._command)

    async def execute(
        self,
        cmd: list[str],
        prompt: str,
        cwd: Path,
        event_data: TranscriptEventData,
        *,
        on_output: Callable[[str], bool] | None = None,
        telemetry_stats: Mapping[str, object] | None = None,
    ) -> str:
        """Return the next scripted transcript and record the call.

        When ``on_output`` is provided it is called once with the transcript
        text (mirrors the real ``AgentRunner.execute`` streaming behaviour).
        """
        _ = (telemetry_stats,)
        self.execute_calls.append((list(cmd), prompt, cwd, event_data))

        if self._exec_queue:
            transcript = self._exec_queue.popleft()
            self._exec_last = transcript
        elif self._exec_last is not None:
            transcript = self._exec_last
        else:
            transcript = _DEFAULT_TRANSCRIPT

        if on_output is not None:
            on_output(transcript)

        return transcript

    async def verify_result(self, worktree_path: Path, branch: str) -> LoopResult:
        """Return the next scripted ``LoopResult`` and record the call.

        Defaults to ``LoopResult(passed=True, summary="OK")`` when no
        result has been scripted.
        """
        self.verify_calls.append((worktree_path, branch))

        if self._verify_queue:
            result = self._verify_queue.popleft()
            self._verify_last = result
            return result
        if self._verify_last is not None:
            return self._verify_last
        return LoopResult(passed=True, summary="OK")
