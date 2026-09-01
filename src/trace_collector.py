"""In-process trace collector for stream_claude_process subprocesses.

Owned by the runner that calls stream_claude_process(). One instance
per `claude -p` subprocess. Accumulates spans in memory and writes a
SubprocessTrace JSON file on finalize().

Failure semantics: every public method is wrapped in try/except +
warning log. Trace collection MUST NOT crash the agent run.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from models import (
    SkillResultRecord,
    SubprocessTrace,
    ToolCallSpan,
    TraceTokenStats,
    TraceToolProfile,
)
from tool_outcome import read_failure

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from events import EventBus

#: Codex item types that terminate a previously-announced call. Enumerated
#: rather than guessed at one name — see `tool_outcome` for why the table is
#: the guess and a miss must be observable.
_CODEX_COMPLETION_TYPES = frozenset(
    {"function_call_output", "tool_call_output", "command_execution"}
)

logger = logging.getLogger("hydraflow.trace_collector")

# Cap on any single captured error string written into a trace.
_MAX_ERROR_CHARS = 500
# Cap on retained stream-level error events — a failing subprocess can emit
# them indefinitely, and the newest are the diagnostic ones.
_MAX_STREAM_ERRORS = 20


def _newest_errors_within(errors: list[str], budget: int) -> str | None:
    """Join stream errors newest-first under *budget*, rendered oldest-first.

    The two halves of this cap used to disagree (#11942). In-memory trimming
    keeps the most recent ``_MAX_STREAM_ERRORS`` — ``del errors[:-N]`` — on the
    stated grounds that "the newest are the diagnostic ones". The write then did
    ``"; ".join(errors)[:budget]``, a FRONT slice, which keeps the earliest and
    silently drops the newest. Three realistic messages (a stack trace, an auth
    failure) reach 500 characters easily, so the persisted ``error`` could show
    stale early text instead of the terminal failure — in the one field that
    reaches disk, since ``SubprocessTrace`` has no ``stream_errors``.

    The newest message is always included, truncated alone if it has to be:
    a summary that drops the reason a run died is worse than a short one. Older
    messages are added while they fit whole, never sliced mid-message, and the
    result reads oldest-to-newest so the sequence still tells a story.
    """
    if not errors:
        return None
    newest = errors[-1][:budget]
    kept = [newest]
    used = len(newest)
    for message in reversed(errors[:-1]):
        cost = len(message) + len("; ")
        if used + cost > budget:
            break
        kept.append(message)
        used += cost
    return "; ".join(reversed(kept)) or None


class TraceCollector:
    """Accumulate spans for one `claude -p` subprocess and write the trace."""

    def __init__(
        self,
        *,
        issue_number: int | None,
        phase: str,
        source: str,
        subprocess_idx: int,
        run_id: int,
        config: HydraFlowConfig,
        event_bus: EventBus | None = None,
    ) -> None:
        self._issue_number = issue_number or 0
        self._phase = phase
        self._source = source
        self._subprocess_idx = subprocess_idx
        self._run_id = run_id
        self._config = config
        self._event_bus = event_bus

        self._started_at = datetime.now(UTC).isoformat()
        self._ended_at: str | None = None

        self.backend: str = "unknown"
        self.tokens = TraceTokenStats(
            prompt_tokens=0,
            completion_tokens=0,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            cache_hit_rate=0.0,
        )
        self.tool_counts: dict[str, int] = {}
        # Keyed strictly by tool NAME. Stream-level failures go to
        # `stream_errors` instead: this dict previously only ever received the
        # literal key "__stream__", so trace_rollup.py's per-tool error
        # breakdown was structurally empty for every trace ever written.
        self.tool_errors: dict[str, int] = {}
        self.stream_errors: list[str] = []
        self.tool_calls: list[ToolCallSpan] = []
        self.skill_results: list[SkillResultRecord] = []
        self.inference_count: int = 0

        # Track open tool_use → tool_result by id, value is monotonic start time
        self._open_tool_starts: dict[str, float] = {}
        # Idempotency guard for finalize() — protects against double-finalize
        # on auth-retry exhaustion + outer except, or any other accidental
        # double-call from the runner lifecycle.
        self._finalized: bool = False

    def record(self, raw_line: str) -> None:
        """Record one parsed JSON line. Never raises."""
        try:
            self._record_inner(raw_line)
        except Exception:
            logger.warning("trace_collector.record failed", exc_info=True)

    def _record_inner(self, raw_line: str) -> None:
        try:
            event = json.loads(raw_line)
        except (json.JSONDecodeError, TypeError):
            return

        event_type = str(event.get("type", ""))
        self._detect_backend(event_type)

        if event_type == "assistant":
            self._handle_assistant(event)
        elif event_type == "user":
            self._handle_user_tool_result(event)
        elif event_type == "result":
            self._handle_result(event)
        elif event_type == "item.completed":
            self._handle_codex_item(event)
        elif event_type in ("message_update", "message_end"):
            self._handle_pi_message(event)
        elif event_type == "tool_execution_start":
            self._handle_pi_tool_start(event)
        elif event_type == "tool_execution_end":
            self._handle_pi_tool_end(event)
        elif event_type == "error":
            self._handle_error(event)

    def _detect_backend(self, event_type: str) -> None:
        if self.backend != "unknown":
            return
        if event_type in ("assistant", "user", "result"):
            self.backend = "claude"
        elif event_type in ("item.completed", "turn.completed"):
            self.backend = "codex"
        elif event_type in (
            "message_update",
            "message_end",
            "tool_execution_start",
            "tool_execution_end",
        ):
            self.backend = "pi"

    def _handle_assistant(self, event: dict[str, Any]) -> None:
        self.inference_count += 1
        self._extract_tokens(
            event.get("usage") or event.get("message", {}).get("usage")
        )

        message = event.get("message", {})
        content = message.get("content", [])
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                self._add_tool_call(block)

    def _handle_user_tool_result(self, event: dict[str, Any]) -> None:
        message = event.get("message", {})
        content = message.get("content", [])
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                tool_use_id = block.get("tool_use_id", "")
                if tool_use_id and tool_use_id in self._open_tool_starts:
                    started = self._open_tool_starts.pop(tool_use_id)
                    duration_ms = max(0, int((time.monotonic() - started) * 1000))
                    # Match by tool_use_id so out-of-order results from
                    # concurrent tool calls are attributed to the correct
                    # span instead of the most-recent pending one.
                    error_text = self._result_error_text(block)
                    for idx in range(len(self.tool_calls) - 1, -1, -1):
                        span = self.tool_calls[idx]
                        if span.tool_use_id == tool_use_id and not span.succeeded:
                            self.tool_calls[idx] = span.model_copy(
                                update={
                                    "duration_ms": duration_ms,
                                    "succeeded": error_text is None,
                                    "error": error_text,
                                }
                            )
                            if error_text is not None:
                                self.tool_errors[span.tool_name] = (
                                    self.tool_errors.get(span.tool_name, 0) + 1
                                )
                            break

    @staticmethod
    def _result_error_text(block: dict[str, Any]) -> str | None:
        """Error text for a failed ``tool_result``, else ``None``.

        ``is_error`` is authoritative — the same rule ``director_sandbox``
        applies to result frames. ``content`` arrives either as a plain string
        or as a list of content blocks.
        """
        if not block.get("is_error"):
            return None
        content = block.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                str(part.get("text", "")) for part in content if isinstance(part, dict)
            )
        return str(content)[:_MAX_ERROR_CHARS] or "(no error text)"

    def _handle_result(self, event: dict[str, Any]) -> None:
        self._extract_tokens(event.get("usage"))
        self._ended_at = datetime.now(UTC).isoformat()

    def _handle_codex_item(self, event: dict[str, Any]) -> None:
        item = event.get("item", {})
        item_type = item.get("type", "")
        if item_type == "agent_message":
            self.inference_count += 1
        elif item_type == "function_call":
            try:
                args = (
                    json.loads(item.get("arguments", "{}"))
                    if item.get("arguments")
                    else {}
                )
            except (json.JSONDecodeError, TypeError):
                args = {}
            self._add_tool_call(
                {
                    "name": item.get("name", "?"),
                    "input": args,
                    "id": item.get("id", ""),
                }
            )
            # A `function_call` item that ALSO carries a terminal status is
            # both the start and the end — Codex reports some tools that way.
            if item.get("status"):
                self._close_codex_span(item)
        elif item_type in _CODEX_COMPLETION_TYPES:
            self._close_codex_span(item)

    def _close_codex_span(self, item: dict[str, Any]) -> None:
        """Close a Codex tool span (#11889).

        `_handle_codex_item` had no completion branch at all, so every Codex
        span stayed ``succeeded=False, duration_ms=0`` forever. That is "never
        closed", not "failed" — and it is why `retro_signals` had to key on
        ``error is not None``: `succeeded` meant a different thing per backend,
        so nothing downstream could read it.
        """
        call_id = str(item.get("call_id") or item.get("id") or "")
        if not call_id:
            return
        started = self._open_tool_starts.pop(call_id, None)
        duration_ms = (
            max(0, int((time.monotonic() - started) * 1000))
            if started is not None
            else 0
        )
        error = read_failure(item)
        for idx in range(len(self.tool_calls) - 1, -1, -1):
            span = self.tool_calls[idx]
            if span.tool_use_id == call_id and not span.succeeded:
                self.tool_calls[idx] = span.model_copy(
                    update={
                        "duration_ms": duration_ms,
                        "succeeded": error is None,
                        "error": error,
                    }
                )
                if error is not None:
                    self.tool_errors[span.tool_name] = (
                        self.tool_errors.get(span.tool_name, 0) + 1
                    )
                break

    def _handle_pi_message(self, event: dict[str, Any]) -> None:
        if event.get("type") == "message_end":
            self.inference_count += 1

    def _handle_pi_tool_start(self, event: dict[str, Any]) -> None:
        self._add_tool_call(
            {
                "name": event.get("toolName", "?"),
                "input": event.get("args", {}),
                "id": event.get("invocationId", ""),
            }
        )

    def _handle_pi_tool_end(self, event: dict[str, Any]) -> None:
        """Close a Pi tool span, reading the event body for failure (#11889).

        This used to flip the span to ``succeeded=True`` on ANY
        ``tool_execution_end`` and read the body for nothing but
        ``invocationId``, so a real Pi tool failure produced no error text, no
        `tool_errors` entry, and no retro signal — while looking identical to a
        success.
        """
        invocation_id = event.get("invocationId", "")
        if invocation_id in self._open_tool_starts:
            started = self._open_tool_starts.pop(invocation_id)
            duration_ms = max(0, int((time.monotonic() - started) * 1000))
            error = read_failure(event)
            for idx in range(len(self.tool_calls) - 1, -1, -1):
                span = self.tool_calls[idx]
                if span.tool_use_id == invocation_id and not span.succeeded:
                    self.tool_calls[idx] = span.model_copy(
                        update={
                            "duration_ms": duration_ms,
                            "succeeded": error is None,
                            "error": error,
                        }
                    )
                    if error is not None:
                        self.tool_errors[span.tool_name] = (
                            self.tool_errors.get(span.tool_name, 0) + 1
                        )
                    break

    def _handle_error(self, event: dict[str, Any]) -> None:
        msg = str(event.get("message", "unknown error"))
        self.stream_errors.append(msg[:_MAX_ERROR_CHARS])
        if len(self.stream_errors) > _MAX_STREAM_ERRORS:
            del self.stream_errors[:-_MAX_STREAM_ERRORS]
        logger.debug("Stream error event recorded: %s", msg)

    def _add_tool_call(self, block: dict[str, Any]) -> None:
        name = str(block.get("name", "?"))
        tool_input = block.get("input") or {}
        tool_id = str(block.get("id", ""))
        summary = self._summarize_tool_input(name, tool_input)

        span = ToolCallSpan(
            tool_name=name,
            started_at=datetime.now(UTC).isoformat(),
            duration_ms=0,
            input_summary=summary,
            succeeded=False,
            tool_use_id=tool_id or None,
        )
        self.tool_calls.append(span)
        self.tool_counts[name] = self.tool_counts.get(name, 0) + 1
        if tool_id:
            self._open_tool_starts[tool_id] = time.monotonic()

    @staticmethod
    def _summarize_tool_input(name: str, tool_input: dict[str, Any]) -> str:
        """Reuse activity_parser._summarize_tool when available; fall back otherwise."""
        try:
            from activity_parser import _summarize_tool  # noqa: PLC0415

            return _summarize_tool(name, tool_input)
        except Exception:
            return str(tool_input)[:200]

    def _extract_tokens(self, usage: dict[str, Any] | None) -> None:
        if not isinstance(usage, dict):
            return
        prompt = max(self.tokens.prompt_tokens, int(usage.get("input_tokens", 0) or 0))
        completion = max(
            self.tokens.completion_tokens, int(usage.get("output_tokens", 0) or 0)
        )
        cache_read = max(
            self.tokens.cache_read_tokens,
            int(usage.get("cache_read_input_tokens", 0) or 0),
        )
        cache_create = max(
            self.tokens.cache_creation_tokens,
            int(usage.get("cache_creation_input_tokens", 0) or 0),
        )
        total_input = prompt + cache_read
        cache_hit_rate = (cache_read / total_input) if total_input > 0 else 0.0
        self.tokens = TraceTokenStats(
            prompt_tokens=prompt,
            completion_tokens=completion,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_create,
            cache_hit_rate=round(cache_hit_rate, 4),
        )

    def record_skill_result(
        self,
        skill_name: str,
        *,
        passed: bool,
        attempts: int,
        duration_seconds: float,
        blocking: bool,
    ) -> None:
        """Append a skill loop result. Source of truth for skill effectiveness."""
        try:
            self.skill_results.append(
                SkillResultRecord(
                    skill_name=skill_name,
                    passed=passed,
                    attempts=attempts,
                    duration_seconds=duration_seconds,
                    blocking=blocking,
                )
            )
        except Exception:
            logger.warning("trace_collector.record_skill_result failed", exc_info=True)

    def finalize(self, *, success: bool) -> SubprocessTrace | None:
        """Write the subprocess trace file. Returns the trace or None on failure.

        Idempotent: subsequent calls after the first are no-ops. This guards
        against double-finalize when, e.g., an auth-retry path and an outer
        ``except`` both attempt to finalize the same collector.

        Never raises.
        """
        if self._finalized:
            return None
        self._finalized = True
        try:
            return self._finalize_inner(success=success)
        except Exception:
            logger.warning("trace_collector.finalize failed", exc_info=True)
            return None

    def _finalize_inner(self, *, success: bool) -> SubprocessTrace | None:
        if (
            self.inference_count == 0
            and not self.tool_calls
            and not self.skill_results
            and not self.stream_errors
        ):
            return None

        if self._ended_at is None:
            self._ended_at = datetime.now(UTC).isoformat()

        trace = SubprocessTrace(
            issue_number=self._issue_number,
            phase=self._phase,
            source=self._source,
            run_id=self._run_id,
            subprocess_idx=self._subprocess_idx,
            backend=self.backend,
            started_at=self._started_at,
            ended_at=self._ended_at,
            success=success,
            crashed=not success,
            error=_newest_errors_within(self.stream_errors, _MAX_ERROR_CHARS),
            tokens=self.tokens,
            tools=TraceToolProfile(
                tool_counts=dict(self.tool_counts),
                tool_errors=dict(self.tool_errors),
                total_invocations=sum(self.tool_counts.values()),
            ),
            tool_calls=list(self.tool_calls),
            skill_results=list(self.skill_results),
            inference_count=self.inference_count,
        )

        out_dir = (
            self._config.data_root
            / "traces"
            / str(self._issue_number)
            / self._phase
            / f"run-{self._run_id}"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"subprocess-{self._subprocess_idx}.json"
        out_path.write_text(trace.model_dump_json(indent=2), encoding="utf-8")

        return trace


# ---------------------------------------------------------------------------
# Loop-subprocess trace helper (spec §4.11 point 3)
# ---------------------------------------------------------------------------
#
# Loops (CorpusLearningLoop, ContractRefreshLoop, StagingBisectLoop,
# PrinciplesAuditLoop, FlakeTrackerLoop, SkillPromptEvalLoop,
# FakeCoverageAuditorLoop, RCBudgetLoop, WikiRotDetectorLoop,
# TrustFleetSanityLoop) run outside the `claude -p` stream, so they cannot
# use the class-based `TraceCollector`. This free function writes a
# self-contained loop-kind trace file to `<data_root>/traces/_loops/<slug>/`.
# Every loop plan lazy-imports it via `try/except ImportError` so a missing
# helper degrades gracefully; once this module lands, those imports resolve.

import re  # noqa: E402 — intentionally near helpers to survive ruff unused-import sweeps
import threading  # noqa: E402
from pathlib import Path  # noqa: E402

_STDERR_TRUNC_CAP = 2048
_CONFIG_LOCK = threading.Lock()
# Single-slot mutable container so we can rebind without `global` (PLW0603).
# Index 0 holds the active HydraFlowConfig (or None). Access through
# set_active_config / _current_config, which take _CONFIG_LOCK.
_ACTIVE_CONFIG_SLOT: list[HydraFlowConfig | None] = [None]


def set_active_config(config: HydraFlowConfig | None) -> None:
    """Register the process-wide active config for free-function helpers.

    Called once during orchestrator startup. Free-function helpers like
    ``emit_loop_subprocess_trace`` read it to resolve ``data_root`` without
    threading a config through every loop subprocess call.
    """
    with _CONFIG_LOCK:
        _ACTIVE_CONFIG_SLOT[0] = config


def _current_config() -> HydraFlowConfig | None:
    with _CONFIG_LOCK:
        return _ACTIVE_CONFIG_SLOT[0]


def get_active_config() -> HydraFlowConfig | None:
    """Public read accessor for the process-wide active config.

    Free-function helpers outside this module (e.g. ``auto_pr``'s pre-flight
    gate, #10013) use it to resolve live config knobs without threading a
    config object through every call-site. Returns None when no orchestrator
    has registered a config (standalone/CLI use, unit tests).
    """
    return _current_config()


def _slug_for_loop(loop: str) -> str:
    slug = re.sub(r"[^a-z0-9]", "_", (loop or "").lower()).strip("_")
    return slug or "unknown"


def _loop_trace_dir(loop: str) -> Path:
    cfg = _current_config()
    if cfg is None:
        raise RuntimeError("No active HydraFlowConfig registered")
    return Path(cfg.data_root) / "traces" / "_loops" / _slug_for_loop(loop)


def emit_loop_subprocess_trace(
    loop: str,
    command: list[str],
    exit_code: int,
    duration_ms: int,
    stderr_excerpt: str | None = None,
) -> None:
    """Emit a per-loop subprocess trace file.

    Writes ``{"kind": "loop", "loop": "<name>", "command": [...], "exit_code":
    N, "duration_ms": N, "stderr": "..."}`` to ``<data_root>/traces/_loops/
    <slug>/run-<iso>.json``. Stderr is tail-truncated to 2048 chars.

    Never raises. A broken filesystem, missing config, or any other error
    is logged at WARNING and swallowed — a loop tick must survive this.
    """
    try:
        cfg = _current_config()
        if cfg is None:
            logger.debug("emit_loop_subprocess_trace: no active config; skipping")
            return

        stderr = stderr_excerpt[-_STDERR_TRUNC_CAP:] if stderr_excerpt else None
        # The helper is invoked after the subprocess finishes (duration_ms is
        # already elapsed), so ``emitted`` is ~the work's END. Back-date to the
        # true start so a consumer's [started_at, started_at + duration_ms]
        # window brackets the work instead of landing one full duration in the
        # future. The filename keeps emit-time for uniqueness/ordering.
        emitted = datetime.now(UTC)
        started_at = (emitted - timedelta(milliseconds=int(duration_ms))).isoformat()
        slug_ts = emitted.strftime("%Y%m%dT%H%M%S%fZ")

        payload = {
            "kind": "loop",
            "loop": loop,
            "command": list(command),
            "exit_code": int(exit_code),
            "duration_ms": int(duration_ms),
            "stderr": stderr,
            "started_at": started_at,
        }

        out_dir = _loop_trace_dir(loop)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"run-{slug_ts}.json"
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        logger.warning("emit_loop_subprocess_trace failed", exc_info=True)
