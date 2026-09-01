"""#11889 — Pi and Codex tool failures never reach a trace span.

`TraceCollector` captures tool errors for the Claude backend only (#11887).
The two other backends are structurally blind:

* `_handle_pi_tool_end` (src/trace_collector.py:240) flips the span to
  ``succeeded=True`` on *any* ``tool_execution_end`` and never touches
  ``error`` or ``tool_errors`` — the event body is read for nothing but
  ``invocationId``.
* `_handle_codex_item` (src/trace_collector.py:205) handles ``function_call``
  but has no completion branch, so a Codex span stays
  ``succeeded=False, duration_ms=0`` forever — "never closed", not "failed".

Consequence: `src/retro_signals.py:_tool_errors` must key on
``error is not None`` because ``succeeded`` means something different per
backend, and a real Pi tool failure produces no retro signal at all.

**Why these pins are dialect-agnostic.** #11889 is explicit that no
authoritative Pi/Codex error shape exists in-repo (`_parse_pi_tool_end` reads
only ``result``; `_parse_codex_item` reads only ``type``/``text``;
`tests/fixtures/stream_json/` holds Claude samples and nothing else), and that
guessing one field name would ship a sentinel that silently never matches. So
each pin feeds *every* plausible dialect to a fresh collector and asserts that
**at least one** is understood. Today none are. Whichever shape the captured
fixture turns out to use, a fix that reads it flips these green. If a fixture
reveals a shape missing from the tables below, add it there — the tables are
this pin's only guess.

**Clause split** (#11889 "Done when"). ``succeeded=False`` is pinned for Pi
only. Codex spans are *already* ``succeeded=False`` because they are never
closed, so that clause is vacuously satisfied there and would pin nothing; the
Codex pins assert ``error``, ``tool_errors`` and closure instead.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from retro_evidence import RetroEvidence  # noqa: E402
from retro_signals import extract  # noqa: E402
from tests.helpers import ConfigFactory
from trace_collector import TraceCollector  # noqa: E402


def _make_collector(tmp_path: Path) -> TraceCollector:
    config = ConfigFactory.create()
    config.data_root = tmp_path
    return TraceCollector(
        issue_number=11889,
        phase="implement",
        source="implementer",
        subprocess_idx=0,
        run_id=1,
        config=config,
        event_bus=None,
    )


def _outcome(collector: TraceCollector) -> tuple[Any, ...]:
    """The three observables #11889 asks for, for the first span."""
    span = collector.tool_calls[0]
    return (span.succeeded, span.error, dict(collector.tool_errors))


# ---------------------------------------------------------------------------
# Pi — `tool_execution_start` / `tool_execution_end`
# ---------------------------------------------------------------------------

PI_TOOL = "Bash"


def _pi_start(invocation_id: str = "p1") -> str:
    return json.dumps(
        {
            "type": "tool_execution_start",
            "toolName": PI_TOOL,
            "args": {"command": "make quality"},
            "invocationId": invocation_id,
        }
    )


def _pi_end(payload: dict[str, Any], invocation_id: str = "p1") -> str:
    return json.dumps(
        {
            "type": "tool_execution_end",
            "toolName": PI_TOOL,
            "invocationId": invocation_id,
            **payload,
        }
    )


BOOM = "make: *** [quality] Error 1"

# Every plausible way a Pi `tool_execution_end` could report failure.
PI_FAILURE_DIALECTS: list[tuple[str, dict[str, Any]]] = [
    ("isError", {"isError": True, "result": BOOM}),
    ("is_error", {"is_error": True, "result": BOOM}),
    ("error-string", {"error": BOOM, "result": ""}),
    ("error-object", {"error": {"message": BOOM}}),
    ("status-error", {"status": "error", "result": BOOM}),
    ("status-failed", {"status": "failed", "result": BOOM}),
    ("success-false", {"success": False, "result": BOOM}),
    ("ok-false", {"ok": False, "result": BOOM}),
    ("outcome-failure", {"outcome": "failure", "result": BOOM}),
    ("state-error", {"state": "error", "result": BOOM}),
    ("exitCode", {"exitCode": 1, "result": BOOM}),
    ("exit_code", {"exit_code": 1, "result": BOOM}),
    ("nested-isError", {"result": {"isError": True, "content": BOOM}}),
    ("nested-error", {"result": {"error": BOOM}}),
    ("nested-status", {"result": {"status": "error", "output": BOOM}}),
    ("nested-success", {"result": {"success": False, "output": BOOM}}),
]

# One event carrying every flat marker at once: whichever field the real fix
# reads, this event says "failed" in it.
PI_ALL_MARKERS: dict[str, Any] = {
    "isError": True,
    "is_error": True,
    "error": BOOM,
    "status": "failed",
    "success": False,
    "ok": False,
    "outcome": "failure",
    "state": "error",
    "exitCode": 1,
    "exit_code": 1,
    "result": BOOM,
}

PI_SUCCESS = {"result": "quality: OK"}


def _run_pi(payload: dict[str, Any], tmp_path: Path) -> TraceCollector:
    collector = _make_collector(tmp_path)
    collector.record(_pi_start())
    collector.record(_pi_end(payload))
    return collector


def test_some_pi_failure_dialect_marks_the_span_not_succeeded(tmp_path: Path):
    outcomes = {
        name: _run_pi(payload, tmp_path).tool_calls[0].succeeded
        for name, payload in PI_FAILURE_DIALECTS
    }

    assert any(succeeded is False for succeeded in outcomes.values()), (
        f"every Pi failure dialect still reports succeeded=True: {outcomes}"
    )


def test_some_pi_failure_dialect_records_error_text_on_the_span(tmp_path: Path):
    outcomes = {
        name: _run_pi(payload, tmp_path).tool_calls[0].error
        for name, payload in PI_FAILURE_DIALECTS
    }

    assert any(error is not None for error in outcomes.values()), (
        f"no Pi failure dialect populates ToolCallSpan.error: {outcomes}"
    )


def test_some_pi_failure_dialect_counts_against_the_tool_name(tmp_path: Path):
    outcomes = {
        name: dict(_run_pi(payload, tmp_path).tool_errors)
        for name, payload in PI_FAILURE_DIALECTS
    }

    assert any(errors == {PI_TOOL: 1} for errors in outcomes.values()), (
        f"no Pi failure dialect increments tool_errors: {outcomes}"
    )


def test_pi_success_and_failure_ends_are_distinguishable(tmp_path: Path):
    """The shape-free statement of the defect: no payload changes the outcome."""
    succeeded = _run_pi(PI_SUCCESS, tmp_path)
    failed = _run_pi(PI_ALL_MARKERS, tmp_path)

    assert _outcome(failed) != _outcome(succeeded), (
        "a tool_execution_end that reports failure in every known dialect is "
        f"recorded identically to a successful one: {_outcome(succeeded)}"
    )


# ---------------------------------------------------------------------------
# Codex — `item.completed`
# ---------------------------------------------------------------------------

CODEX_TOOL = "shell"
CODEX_ID = "c1"


def _codex_call() -> str:
    return json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "function_call",
                "name": CODEX_TOOL,
                "arguments": json.dumps({"command": "make quality"}),
                "id": CODEX_ID,
            },
        }
    )


def _item_completed(item: dict[str, Any]) -> dict[str, Any]:
    return {"type": "item.completed", "item": item}


# Every plausible way Codex could signal that the call above finished OK.
CODEX_SUCCESS_COMPLETIONS: list[tuple[str, dict[str, Any]]] = [
    (
        "function_call_output/call_id",
        _item_completed(
            {"type": "function_call_output", "call_id": CODEX_ID, "output": "ok"}
        ),
    ),
    (
        "function_call_output/id",
        _item_completed(
            {"type": "function_call_output", "id": CODEX_ID, "output": "ok"}
        ),
    ),
    (
        "tool_call_output",
        _item_completed({"type": "tool_call_output", "id": CODEX_ID, "output": "ok"}),
    ),
    (
        "function_call/status",
        _item_completed(
            {
                "type": "function_call",
                "id": CODEX_ID,
                "name": CODEX_TOOL,
                "status": "completed",
                "output": "ok",
            }
        ),
    ),
    (
        "command_execution",
        _item_completed(
            {
                "type": "command_execution",
                "id": CODEX_ID,
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": "ok",
            }
        ),
    ),
    ("turn.completed", {"type": "turn.completed"}),
]

# ... and every plausible way it could signal that the call failed.
CODEX_FAILURE_COMPLETIONS: list[tuple[str, dict[str, Any]]] = [
    (
        "output/is_error",
        _item_completed(
            {
                "type": "function_call_output",
                "call_id": CODEX_ID,
                "output": BOOM,
                "is_error": True,
            }
        ),
    ),
    (
        "output/success-false",
        _item_completed(
            {
                "type": "function_call_output",
                "call_id": CODEX_ID,
                "output": BOOM,
                "success": False,
            }
        ),
    ),
    (
        "output/error",
        _item_completed(
            {"type": "function_call_output", "id": CODEX_ID, "error": BOOM}
        ),
    ),
    (
        "function_call/status-failed",
        _item_completed(
            {
                "type": "function_call",
                "id": CODEX_ID,
                "name": CODEX_TOOL,
                "status": "failed",
                "output": BOOM,
            }
        ),
    ),
    (
        "command_execution/status-failed",
        _item_completed(
            {
                "type": "command_execution",
                "id": CODEX_ID,
                "status": "failed",
                "exit_code": 1,
                "aggregated_output": BOOM,
            }
        ),
    ),
    (
        "command_execution/exit_code",
        _item_completed(
            {
                "type": "command_execution",
                "id": CODEX_ID,
                "exit_code": 1,
                "aggregated_output": BOOM,
            }
        ),
    ),
    (
        "error-item",
        _item_completed({"type": "error", "id": CODEX_ID, "message": BOOM}),
    ),
]


def _run_codex(
    completion: dict[str, Any], tmp_path: Path, *, pause: float = 0.0
) -> TraceCollector:
    collector = _make_collector(tmp_path)
    collector.record(_codex_call())
    if pause:
        time.sleep(pause)
    collector.record(json.dumps(completion))
    return collector


def test_some_codex_completion_closes_the_span(tmp_path: Path):
    outcomes = {
        name: [span.succeeded for span in _run_codex(event, tmp_path).tool_calls]
        for name, event in CODEX_SUCCESS_COMPLETIONS
    }

    assert any(any(spans) for spans in outcomes.values()), (
        f"no Codex completion event closes the function_call span: {outcomes}"
    )


def test_some_codex_completion_gives_the_span_a_real_duration(tmp_path: Path):
    outcomes = {
        name: [
            span.duration_ms
            for span in _run_codex(event, tmp_path, pause=0.02).tool_calls
        ]
        for name, event in CODEX_SUCCESS_COMPLETIONS
    }

    assert any(any(d > 0 for d in spans) for spans in outcomes.values()), (
        f"every Codex span keeps duration_ms=0 after a 20ms tool call: {outcomes}"
    )


def test_some_codex_failure_records_error_text_on_the_span(tmp_path: Path):
    outcomes = {
        name: [span.error for span in _run_codex(event, tmp_path).tool_calls]
        for name, event in CODEX_FAILURE_COMPLETIONS
    }

    assert any(any(e is not None for e in spans) for spans in outcomes.values()), (
        f"no Codex failure dialect populates ToolCallSpan.error: {outcomes}"
    )


def test_some_codex_failure_counts_against_the_tool_name(tmp_path: Path):
    outcomes = {
        name: dict(_run_codex(event, tmp_path).tool_errors)
        for name, event in CODEX_FAILURE_COMPLETIONS
    }

    assert any(errors == {CODEX_TOOL: 1} for errors in outcomes.values()), (
        f"no Codex failure dialect increments tool_errors: {outcomes}"
    )


# ---------------------------------------------------------------------------
# Downstream consequence — the reason #11889 exists
# ---------------------------------------------------------------------------


def test_failed_pi_tool_call_reaches_the_retro_as_a_tool_error_signal(tmp_path: Path):
    """`retro_signals` keys on ``error``, so a blind collector silences it."""
    collector = _run_pi(PI_ALL_MARKERS, tmp_path)
    trace = collector.finalize(success=False)

    assert trace is not None
    signals = extract([RetroEvidence(issue_number=11889, traces=[trace])])

    assert [s for s in signals if s.family == "tool_error"], (
        "a Pi tool call that failed produces no tool_error retro signal"
    )


# ---------------------------------------------------------------------------
# Controls — green before the fix and after it
# ---------------------------------------------------------------------------


def test_control_claude_failure_is_captured_today(tmp_path: Path):
    """Liveness: the collector, the harness and the assertions all work."""
    collector = _make_collector(tmp_path)
    collector.record(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "Bash",
                            "input": {"command": "make quality"},
                        }
                    ]
                },
            }
        )
    )
    collector.record(
        json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "t1",
                            "is_error": True,
                            "content": BOOM,
                        }
                    ]
                },
            }
        )
    )

    assert _outcome(collector) == (False, BOOM, {"Bash": 1})


def test_control_successful_pi_tool_end_is_not_an_error(tmp_path: Path):
    """Counter-pin: the fix must discriminate, not mark everything failed."""
    collector = _run_pi(PI_SUCCESS, tmp_path)
    span = collector.tool_calls[0]

    assert (span.error, dict(collector.tool_errors)) == (None, {})


def test_control_successful_codex_completion_is_not_an_error(tmp_path: Path):
    """Same counter-pin on the Codex side, across every completion dialect."""
    outcomes = {
        name: dict(_run_codex(event, tmp_path).tool_errors)
        for name, event in CODEX_SUCCESS_COMPLETIONS
    }

    assert all(errors == {} for errors in outcomes.values()), outcomes
