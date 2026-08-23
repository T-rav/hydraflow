"""Shared subprocess streaming utilities for agent runners."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

import httpx

import process_group
from activity_parser import ActivityParser, get_activity_parser
from agent_rate_backoff import classify_agent_outcome, get_agent_rate_backoff
from docker_runner import get_docker_runner
from events import EventBus, EventType, HydraFlowEvent
from execution import HostRunner, SimpleResult, SubprocessRunner, get_default_runner
from gateway_mint_client import (
    GatewayControlClient,
    GatewayMintError,
    GatewayMintRequest,
    GatewayMintV2Request,
    _gateway_ttl_seconds,
    _GatewayKeyLease,
    _HttpGatewayControlClient,
    _RoutedHarnessEnv,
    _validate_gateway_credential,
    revoke_gateway_key,
)
from model_pricing import USAGE_SHAPE_OPENAI_COMPAT, usage_shape_for_tool
from models import TranscriptEventData, TranscriptLinePayload
from process_group import kill_process_group
from prompt_gate import PromptGateBlockedError, gate_prompt
from prompt_telemetry import parse_command_tool_model
from stream_parser import StreamParser, parse_result_envelope
from subprocess_util import (
    PROVIDER_ANTHROPIC,
    CreditExhaustedError,
    is_credit_exhaustion,
    make_clean_env,
    parse_credit_resume_time,
    scrub_gateway_spawn_env,
)

if TYPE_CHECKING:
    from agent_cli import AgentTool
    from config import HydraFlowConfig
    from route_enforcement import EnforcedRoute
    from trace_collector import TraceCollector

logger = logging.getLogger("hydraflow.runner_utils")

# Size of the accumulated-display tail scanned per line for a mid-run credit
# signal (#10597). Comfortably larger than the longest credit phrase plus its
# resume clause (~65 chars), so a cap message split across a few consecutive
# same-message stream deltas is still caught, while keeping the per-line scan
# O(1) instead of re-scanning the whole (growing) transcript.
_CREDIT_SCAN_TAIL_CHARS = 512


class AuthenticationRetryError(RuntimeError):
    """Raised when the agent CLI reports authentication_failed.

    Treated as retryable — OAuth token refresh can fail transiently.
    """


# Backend-specific auth-failure signatures. Keep these conservative — false
# positives turn real agent output into spurious retries. These broad patterns
# are matched ONLY in the CLI's stderr (its own error channel). An agent that
# reviews or fixes auth code legitimately emits "AuthenticationError" /
# "authentication failed" in its STDOUT response, and matching that text (with
# no exit-code gate) killed valid runs as bogus "auth failures" that retried 3x
# then failed.
_AUTH_FAILURE_PATTERNS = (
    "authentication_failed",  # claude-code stream-json
    "Please set an Auth method",  # gemini-cli startup
    "AuthenticationError",  # SDK exception traceback
)
# Matched in stdout (the agent's own output) — confined to JUST the claude
# stream-json error token so the agent's prose mentions of the broad patterns
# above (e.g. the class name "AuthenticationError") do not trip it.
_AUTH_FAILURE_STDOUT_PATTERNS = ("authentication_failed",)


def _is_auth_failure(stderr: str, stdout: str) -> bool:
    """Return True if the CLI itself reported a retryable auth failure.

    Broad patterns (incl. the class name ``AuthenticationError``) match only in
    *stderr* — the CLI's own error channel. *stdout* (the agent's response, where
    a reviewer/triage run legitimately mentions those words) is matched only on
    claude's structured stream-json error token ``authentication_failed``.
    Exit code is deliberately NOT gated on: claude reports auth failures in-band
    via stream-json and can still exit 0.
    """
    if any(pattern in stderr for pattern in _AUTH_FAILURE_PATTERNS):
        return True
    return any(pattern in stdout for pattern in _AUTH_FAILURE_STDOUT_PATTERNS)


@dataclass(frozen=True, slots=True)
class StreamConfig:
    """Rarely-varying options for :func:`stream_claude_process`."""

    on_output: Callable[[str], bool] | None = None
    timeout: float = 3600.0
    runner: SubprocessRunner | None = None
    usage_stats: dict[str, object] | None = field(default=None)
    gh_token: str = ""
    trace_collector: TraceCollector | None = None
    # #9895: when False, credit exhaustion is detected from stderr (the
    # CLI's own signal) only — agent stdout prose is NOT scanned. Runners
    # that analyze failure transcripts (DiagnosticRunner) quote credit-error
    # prose routinely; scanning it raised a false global CreditExhaustedError
    # on essentially every diagnostic run (mirrors the _is_auth_failure rule).
    credit_prose_scan: bool = True
    # Per-spawn env overrides that point the Claude CLI at a harness backend
    # (from resolve_harness_env). Empty for the native Anthropic endpoint — the
    # main workers get a pristine env. Merged AFTER make_clean_env so the
    # ANTHROPIC_* keys survive the strip.
    harness_env: dict[str, str] = field(default_factory=dict)
    # Transport is separate from the billing provider.  In gateway mode the
    # latter remains anthropic/zai while this field triggers the final
    # credential scrub at the host boundary.
    harness_transport: str = "claude"
    # The resolved billing provider for this spawn ("anthropic"/"zai") so a
    # credit-out is scoped to the right backend rather than a global kill switch.
    provider: str = "claude"


def _route_prompt_to_cmd(cmd: list[str], prompt: str) -> tuple[list[str], int]:
    """Decide how to deliver *prompt* to the CLI subprocess.

    Returns ``(cmd_to_run, stdin_mode)`` where *stdin_mode* is either
    ``asyncio.subprocess.DEVNULL`` (prompt embedded in *cmd_to_run*) or
    ``asyncio.subprocess.PIPE`` (caller must write *prompt* to stdin).
    """
    use_codex_exec = len(cmd) >= 2 and cmd[0] == "codex" and cmd[1] == "exec"
    use_claude_print = bool(cmd) and cmd[0] == "claude" and "-p" in cmd
    use_prompt_arg = use_codex_exec or use_claude_print
    if use_prompt_arg:
        if use_claude_print:
            # Claude requires the prompt immediately after -p; placing it at
            # the end causes CLI errors.
            idx = cmd.index("-p")
            cmd_to_run = [*cmd[: idx + 1], prompt, *cmd[idx + 1 :]]
        else:
            # Codex exec: prompt is a trailing positional argument.
            cmd_to_run = [*cmd, prompt]
        return cmd_to_run, asyncio.subprocess.DEVNULL
    return cmd, asyncio.subprocess.PIPE


def _post_stream_result(
    *,
    raw_lines: list[str],
    accumulated_text: str,
    result_text: str,
    early_killed: bool,
    returncode: int | None,
    stderr_text: str,
    parser: StreamParser,
    config: StreamConfig,
    logger: logging.Logger,
) -> str:
    """Validate post-stream state, check for errors, and assemble the transcript.

    Raises :class:`AuthenticationRetryError` or :class:`CreditExhaustedError`
    when the raw output indicates a retryable auth or billing failure
    (skipped when *early_killed* is ``True``).
    """
    if not early_killed and returncode != 0:
        logger.warning(
            "Process exited with code %d: %s",
            returncode,
            stderr_text[:500],
        )

    # Skip auth/credit checks when early_killed — killing the process can cause
    # in-flight API requests to fail with spurious errors.
    raw_output = "\n".join(raw_lines)
    # Detect auth failure from the CLI's OWN signal — the broad patterns in
    # stderr, or claude's structured stream-json token in stdout — NOT from the
    # agent's prose. Scanning the whole transcript for "AuthenticationError"
    # killed reviewer/triage runs that merely mentioned auth as a bogus "auth
    # failure" (retried 3x then failed).
    if not early_killed and _is_auth_failure(stderr_text, raw_output):
        raise AuthenticationRetryError(
            "Agent CLI authentication failed — check the provider's auth "
            "(ANTHROPIC_API_KEY / CLAUDE_CODE_OAUTH_TOKEN / GEMINI_API_KEY / "
            "~/.gemini/settings.json / CODEX_HOME)"
        )

    combined = (
        f"{stderr_text}\n{accumulated_text}"
        if config.credit_prose_scan
        else stderr_text
    )

    # Record the run's outcome for the rate-aware agent backoff (#10289). A
    # truncated mid-run failure (rc != 0 with no terminal result frame) is the
    # depleted-rate-window signature — distinct from credit exhaustion (a lone
    # probe on the same auth succeeds) — and repeated occurrences throttle
    # spawning. Auth failures already raised above and are excluded; credit
    # exhaustion is classified but deliberately does NOT feed the rate backoff.
    # Conservatively defaulted: the engine is disabled unless explicitly wired,
    # so this call is inert by default and can never wedge the pipeline.
    if not early_killed:
        get_agent_rate_backoff().record_outcome(
            classify_agent_outcome(
                returncode=returncode,
                has_result_frame=bool(result_text),
                output_text=combined,
                early_killed=early_killed,
            )
        )

    if not early_killed and is_credit_exhaustion(combined):
        resume_at = parse_credit_resume_time(combined)
        # Tag the resolved backend so the pause is scoped to loops on it — a GLM
        # cap on a zai-routed agentic spawn must not halt Claude work (#9807).
        # Authoritative when the CLI's OWN stderr carries the signal — the process's
        # direct termination, ground truth for a real cap (session / weekly /
        # balance). A match found ONLY in stdout prose (credit_prose_scan) is a
        # diagnostic/reviewer run quoting a prior cap in its analysis, so it is NOT
        # authoritative and must be corroborated by the orchestrator's live probe
        # before a global pause. Crucially, the auth probe cannot detect a *weekly*
        # limit (the key stays valid), so a genuine weekly signal on stderr must
        # skip the probe or it is wrongly discarded (#10558/#9895).
        authoritative = is_credit_exhaustion(stderr_text)
        raise CreditExhaustedError(
            "API credit limit reached",
            resume_at=resume_at,
            provider=normalize_provider(config.provider),
            authoritative=authoritative,
        )

    if config.usage_stats is not None:
        config.usage_stats.update(parser.usage_snapshot)

    transcript = result_text or accumulated_text.rstrip("\n") or "\n".join(raw_lines)

    if not transcript.strip() and stderr_text:
        logger.warning(
            "Process produced empty stdout (rc=%d), stderr: %s",
            returncode or 0,
            stderr_text[:500],
        )

    return transcript


async def _stream_and_collect(
    proc: asyncio.subprocess.Process,
    stderr_task: asyncio.Task[bytes],
    event_bus: EventBus,
    event_data: TranscriptEventData,
    parser: StreamParser,
    activity_parser: ActivityParser,
    logger: logging.Logger,
    config: StreamConfig,
) -> str:
    """Read *proc* stdout, publish events, and assemble the transcript."""
    raw_lines: list[str] = []
    result_text = ""
    accumulated_text = ""
    early_killed = False

    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode(errors="replace").rstrip("\n")
        raw_lines.append(line)
        if not line.strip():
            continue

        display, result = parser.parse(line)
        if result is not None:
            result_text = result

        if display.strip():
            accumulated_text += display + "\n"
            line_data: TranscriptLinePayload = {**event_data, "line": display}
            await event_bus.publish(
                HydraFlowEvent(type=EventType.TRANSCRIPT_LINE, data=line_data)
            )

        if (
            config.on_output is not None
            and not early_killed
            and config.on_output(accumulated_text)
        ):
            early_killed = True
            # Group kill (self-suppressing): the early-kill previously
            # reaped only the direct child, leaking its group (#9911).
            _kill_proc_group(proc)
            break

        # Fail-fast on a MID-RUN credit-exhaustion signal (#10597). When the
        # weekly/session cap is hit partway through a run the CLI does not exit:
        # it sits in api-retry/backoff, emits the limit line into stdout, but
        # never closes the stream — so this read loop would block until the
        # 3600s hard cap fires (~1h burned per attempt). Worse, that generic
        # hard-timeout surfaces as a plain RuntimeError the orchestrator counts
        # as a failed attempt, consuming the retry budget; raising here routes
        # the signal through reraise_on_credit_or_bug to the global pause/park
        # (with an attempt refund) instead. Placed AFTER the on_output early-kill
        # so an early-kill's legitimate credit-phrase content stays exempt
        # (mirrors _post_stream_result's early_killed skip). Gated on
        # credit_prose_scan for the SAME reason as the post-stream check
        # (#9895): runners that quote credit-error prose (DiagnosticRunner) must
        # not self-trip. Scans a bounded tail of the accumulated display text —
        # the exact surface the post-stream check inspects — so the cap phrase
        # is caught even when it streams in split across same-message deltas,
        # while adding no new false-positive exposure beyond earlier detection.
        credit_tail = accumulated_text[-_CREDIT_SCAN_TAIL_CHARS:]
        if config.credit_prose_scan and is_credit_exhaustion(credit_tail):
            _kill_proc_group(proc)
            with contextlib.suppress(ProcessLookupError, OSError):
                await proc.wait()
            raise CreditExhaustedError(
                "API credit limit reached (detected mid-run)",
                resume_at=parse_credit_resume_time(credit_tail),
            )

        # Emit structured activity event (additive — does not replace TRANSCRIPT_LINE)
        try:
            activity = activity_parser.parse(line)
            if activity is not None:
                activity["issue"] = event_data.get("issue", 0)
                activity["source"] = event_data.get("source", "unknown")
                await event_bus.publish(
                    HydraFlowEvent(type=EventType.AGENT_ACTIVITY, data=activity)
                )
        except Exception:
            logger.warning("Activity parsing failed", exc_info=True)

        if config.trace_collector is not None:
            config.trace_collector.record(line)

    # --- Post-stream validation and result assembly ---
    stderr_bytes = await stderr_task
    # After an early kill the process may already be reaped, so waiting on it can
    # raise ProcessLookupError; suppress it so cleanup never escapes.
    with contextlib.suppress(ProcessLookupError, OSError):
        await proc.wait()
    stderr_text = stderr_bytes.decode(errors="replace").strip()

    return _post_stream_result(
        raw_lines=raw_lines,
        accumulated_text=accumulated_text,
        result_text=result_text,
        early_killed=early_killed,
        returncode=proc.returncode,
        stderr_text=stderr_text,
        parser=parser,
        config=config,
        logger=logger,
    )


async def stream_claude_process(
    *,
    cmd: list[str],
    prompt: str,
    cwd: Path,
    active_procs: set[asyncio.subprocess.Process],
    event_bus: EventBus,
    event_data: TranscriptEventData,
    logger: logging.Logger,
    config: StreamConfig = StreamConfig(),
) -> str:
    """Run an agent subprocess and stream its output.

    Parameters
    ----------
    cmd:
        Command to execute (e.g. ``["claude", "-p", ...]`` or ``["codex", "exec", ...]``).
    prompt:
        Prompt text for the agent. Passed via stdin for Claude-style commands;
        passed as a positional argument for Codex `exec`.
    cwd:
        Working directory for the subprocess.
    active_procs:
        Shared set for tracking active processes (for terminate).
    event_bus:
        For publishing ``TRANSCRIPT_LINE`` events.
    event_data:
        Base dict for event data (runner-specific keys like ``issue``/``pr``/``source``).
        ``"line"`` is added automatically per output line.
    logger:
        Caller's logger for warnings (preserves per-runner log context).
    config:
        Optional streaming configuration (callbacks, timeout, runner, etc.).

    Returns
    -------
    str
        The transcript string, using the fallback chain:
        result_text → accumulated_text → raw_lines.
    """
    env = make_clean_env(config.gh_token)
    if config.harness_transport == _GATEWAY:
        env = scrub_gateway_spawn_env(env)
    runner = config.runner or get_default_runner()
    cmd_to_run, stdin_mode = _route_prompt_to_cmd(cmd, prompt)

    # Rate-aware backpressure (#10289): if repeated mid-run failures have
    # engaged the backoff, delay this spawn instead of hammering a depleted
    # rate window. Inert (no delay) unless the engine is explicitly enabled.
    await get_agent_rate_backoff().wait_if_throttled()

    proc = await runner.create_streaming_process(
        cmd_to_run,
        cwd=str(cwd),
        env=env,
        stdin=stdin_mode,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=1024 * 1024,  # 1 MB — stream-json lines can exceed 64 KB default
        start_new_session=True,  # Own process group for reliable cleanup
        # #11263: the harness backend override travels as its OWN param — the
        # env= dict is deliberately ignored by DockerRunner, which silently
        # stranded rerouted glm spawns on the native Anthropic endpoint.
        harness_env=config.harness_env or None,
    )
    active_procs.add(proc)
    _ALL_TRACKED_PROCS.add(proc)

    stderr_task: asyncio.Task[bytes] | None = None
    try:
        assert proc.stdout is not None
        assert proc.stderr is not None

        if stdin_mode == asyncio.subprocess.PIPE:
            assert proc.stdin is not None
            proc.stdin.write(prompt.encode())
            await proc.stdin.drain()
            proc.stdin.close()

        stderr_task = asyncio.create_task(proc.stderr.read())

        parser = StreamParser()
        _backend = "codex" if cmd and cmd[0] == "codex" else "claude"
        activity_parser = get_activity_parser(_backend)

        return await asyncio.wait_for(
            _stream_and_collect(
                proc,
                stderr_task,
                event_bus,
                event_data,
                parser,
                activity_parser,
                logger,
                config,
            ),
            timeout=config.timeout,
        )
    except TimeoutError as exc:
        # The process may already be dead/reaped; killing/waiting on a gone
        # process raises ProcessLookupError out of the cleanup path. Mirror the
        # guard in terminate_processes().
        with contextlib.suppress(ProcessLookupError, OSError):
            _kill_proc_group(proc)
            await proc.wait()
        raise RuntimeError(f"Agent process timed out after {config.timeout}s") from exc
    except asyncio.CancelledError:
        # On cancellation the process may already have exited; the group
        # kill is self-suppressing (#9911: group, not just the child).
        _kill_proc_group(proc)
        raise
    finally:
        if stderr_task is not None and not stderr_task.done():
            stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)
        active_procs.discard(proc)
        _ALL_TRACKED_PROCS.discard(proc)


def _kill_proc_group(proc: asyncio.subprocess.Process) -> None:
    """SIGKILL *proc*'s whole process group (best-effort, never raises).

    Delegates to the single guarded primitive (#9641) — see
    ``process_group.kill_process_group`` for the mock-pid/pid-0 hazard
    this guard exists for.
    """
    kill_process_group(proc)


def terminate_processes(active_procs: set[asyncio.subprocess.Process]) -> None:
    """Kill all processes in *active_procs* and their process groups."""
    for proc in list(active_procs):
        _kill_proc_group(proc)


# #9911: runtime-wide registry of every live agent subprocess. Per-caller
# ``active_procs`` ownership is fragmented (four runners the stop path
# terminates, plus acceptance_criteria / verification_judge / sentry /
# report_issue sets it never reached — two of those owners have no
# terminate() at all), so stopping the runtime orphaned their children to
# launchd for the length of a pytest/make run. stream_claude_process
# registers every spawn here; the stop/shutdown path reaps the union.
_ALL_TRACKED_PROCS: set[asyncio.subprocess.Process] = process_group._TRACKED


def reap_all_tracked_processes() -> int:
    """SIGKILL the process group of every tracked live subprocess (#9911).

    Delegates to the shared registry in :mod:`process_group` — run_simple
    children register there too, so the stop path sees every spawn path.
    """
    return process_group.reap_all_tracked()


# ---------------------------------------------------------------------------
# Telemetry + credit contract for NON-central spawn paths (WS-2.2 / ADR-0086)
#
# PromptTelemetry is recorded centrally by BaseRunner._execute and
# BaseSubprocessRunner.run. Spawners that bypass both — calling
# stream_claude_process or build_lightweight_command + run_simple directly —
# produce LLM inferences invisible to the cost cap / ROI dashboard, and the
# lightweight (run_simple) path never raises CreditExhaustedError, so credit
# exhaustion is silently swallowed as rc != 0. These two helpers give those
# callers the same telemetry + credit contract the central runners have, so
# every LLM spawn is cost-visible and pauses on the billing signal.
#
# Containment is enforced by tests/test_telemetry_source_completeness.py and
# tests/test_subprocess_runner_contract_completeness.py: no module outside the
# approved recording set may call the raw spawn primitives directly.
# ---------------------------------------------------------------------------


def _as_opt_int(value: object) -> int | None:
    """Coerce an event-data ``issue``/``pr`` value to int, or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


def raise_if_credit_exhausted(
    stdout: str, stderr: str, tool: str, *, provider: str = "claude"
) -> None:
    """Raise :class:`CreditExhaustedError` if lightweight CLI output signals credit-out.

    ``run_simple`` returns a ``SimpleResult`` and never raises on credit
    exhaustion (it surfaces as ``rc != 0`` text), so the lightweight path must
    inspect the output. Mirrors the streaming path's credit check in
    :func:`_post_stream_result`.

    *provider* is the role's resolved backend dial. It is normalized to the
    billing identity and tagged on the error so the orchestrator scopes the
    pause to loops on that backend — a z.ai cap must not halt Claude work, and
    vice-versa (#9807). Defaults to ``"claude"`` (→ ``"anthropic"``) so every
    existing CLI call site stays Anthropic-scoped without change.
    """
    for blob in (stdout, stderr):
        if blob and is_credit_exhaustion(blob):
            # The lightweight CLI's own output IS the process's termination
            # signal (no agent-analysis loop that could merely quote a prior
            # cap), so this is authoritative — the orchestrator pauses without
            # a probe that cannot see a weekly-limit exhaustion (#10558).
            raise CreditExhaustedError(
                f"{tool} CLI signaled credit exhaustion",
                resume_at=parse_credit_resume_time(blob),
                provider=normalize_provider(provider),
                authoritative=True,
            )


def record_inference_telemetry(
    config: HydraFlowConfig,
    *,
    source: str,
    cmd: list[str],
    prompt: str,
    transcript: str,
    duration_s: float,
    success: bool,
    issue_number: int | None = None,
    pr_number: int | None = None,
    session_id: str | None = None,
    stats: dict[str, object] | None = None,
    usage_shape: str | None = None,
) -> None:
    """Best-effort :class:`PromptTelemetry` record for non-central spawn paths.

    Never raises — a telemetry write failure must not crash the spawn that
    produced it (matches the central runners' best-effort recording).

    ``usage_shape`` stamps how the counts were produced (see
    :func:`model_pricing.usage_shape_for_tool`); when omitted it is derived
    from the ``cmd`` head, which for these wrappers is the real producer
    (CLI name, ``gateway``, or the one-shot provider name).
    """
    from prompt_telemetry import PromptTelemetry  # noqa: PLC0415

    try:
        tool, model = parse_command_tool_model(cmd)
        PromptTelemetry(config).record(
            source=source,
            tool=tool,
            model=model,
            issue_number=issue_number,
            pr_number=pr_number,
            session_id=session_id,
            prompt_chars=len(prompt),
            transcript_chars=len(transcript),
            duration_seconds=duration_s,
            success=success,
            stats=stats,
            usage_shape=(
                usage_shape if usage_shape is not None else usage_shape_for_tool(tool)
            ),
        )
    except Exception:
        logger.warning(
            "inference telemetry write failed for source=%s", source, exc_info=True
        )


async def stream_claude_with_telemetry(
    *,
    config: HydraFlowConfig,
    cmd: list[str],
    prompt: str,
    cwd: Path,
    active_procs: set[asyncio.subprocess.Process],
    event_bus: EventBus,
    event_data: TranscriptEventData,
    logger: logging.Logger,
    stream_config: StreamConfig = StreamConfig(),
    issue_number: int | None = None,
    pr_number: int | None = None,
    issue_labels: Sequence[str] = (),
    provider: str = "claude",
) -> str:
    """Stream an agent subprocess AND record prompt/inference telemetry.

    Thin wrapper over :func:`stream_claude_process` that records one
    :class:`PromptTelemetry` row in a ``finally`` (so the spend is visible to
    the cost cap / ROI dashboard on success AND failure), mirroring
    ``BaseRunner._execute``. Credit/auth signals raised by
    ``stream_claude_process`` propagate unchanged — this wrapper never
    swallows them.

    Direct ``stream_claude_process`` callers that are NOT one of the central
    runners (``BaseRunner``/``BaseSubprocessRunner``) MUST use this wrapper so
    no LLM inference is invisible to telemetry.

    *issue_labels* feeds the CH-6 gate's upward-only ``data-class:`` label
    elevation. Callers with an issue in scope MUST pass its labels
    (``issue.labels`` / ``issue.tags``); without them only the repo-declared
    class is enforced.
    """
    # CH-6 data-governance gate (#9734): redact/block BEFORE spawn. A
    # regulated-class block raises pre-spawn — nothing was sent, no telemetry
    # row — and propagates to the caller's failure path (fail closed).
    gate_tool, gate_model = parse_command_tool_model(cmd)
    gated = gate_prompt(
        prompt,
        config=config,
        source=str(event_data.get("source", "unknown")),
        tool=gate_tool,
        issue_number=(
            issue_number
            if issue_number is not None
            else _as_opt_int(event_data.get("issue"))
        ),
        issue_labels=issue_labels,
    )
    prompt = gated.prompt

    # Capture usage stats even when the caller passed no collector, so
    # token-accurate cost lands in telemetry when the stream reports it.
    stats = stream_config.usage_stats
    if stats is None:
        stats = {}
        stream_config = replace(stream_config, usage_stats=stats)

    # The fleet ratchet is a deployment opt-in.  It closes direct CLI call-site
    # gaps without changing safe defaults before the gateway is deployed.
    transport_provider = provider
    if (
        getattr(config, "gateway_fleet_ratchet_enabled", False) is True
        and provider == "claude"
        and gate_tool == "claude"
    ):
        transport_provider = _GATEWAY
    if transport_provider == _GATEWAY and gate_tool != "claude":
        raise ValueError(
            f"provider 'gateway' requires the Claude harness, got {gate_tool!r}"
        )

    # Work attribution for the gateway mint AND the telemetry row below: an
    # explicit kwarg wins, else the event payload's ``issue`` / ``pr``.
    attributed_issue = (
        issue_number
        if issue_number is not None
        else _as_opt_int(event_data.get("issue"))
    )
    attributed_pr = (
        pr_number if pr_number is not None else _as_opt_int(event_data.get("pr"))
    )
    # Routing shadow (#11536, ADR-0139): the fourth governed spawn seam. Like
    # run_lightweight_agent it takes its dial as a `provider=` argument and then
    # applies the fleet ratchet, so with the ratchet on this traffic is *gateway*
    # transport — exactly what a policy would bind. Observation only; the
    # transport is already resolved above.
    from hydraflow_gateway.routing_policy import RequestFace
    from route_enforcement import canary_armed, enforce_canary_route
    from route_shadow import dialled_route_stages, record_dialled_route_shadow

    telemetry_source = str(event_data.get("source", "unknown"))
    await asyncio.to_thread(
        record_dialled_route_shadow,
        config=config,
        principal_id=telemetry_source,
        requested_provider=provider,
        transport_provider=transport_provider,
        model=gate_model,
        request_face=RequestFace.AGENTIC,
        issue_number=attributed_issue,
        pr_number=attributed_pr,
    )
    # Enforcement canary (#11539, ADR-0141): None outside the armed repository,
    # and this seam does not own its argv — the caller built it — so the rewrite
    # goes through the same ``rewrite_command_model`` writer every other routing
    # stage uses, and ``gate_model`` follows it so the mint and the telemetry row
    # cannot disagree with what the child was actually spawned with.
    route = None
    if canary_armed(config):
        route = await asyncio.to_thread(
            enforce_canary_route,
            config=config,
            principal_id=telemetry_source,
            stages=dialled_route_stages(
                config=config,
                requested_provider=provider,
                transport_provider=transport_provider,
            ),
            final_provider=transport_provider,
            final_model=gate_model,
            request_face=RequestFace.AGENTIC,
        )
    if route is not None:
        cmd = route.apply_to_command(cmd)
        gate_tool, gate_model = parse_command_tool_model(cmd)
    # Point the CLI at the role's harness backend for this spawn only (empty for
    # native Anthropic — the main workers stay pristine), and carry the resolved
    # provider so a credit-out is scoped to the right backend.
    harness_env = await resolve_harness_env(
        transport_provider,
        config,
        model=gate_model,
        source=telemetry_source,
        session_id=getattr(event_bus, "current_session_id", None),
        timeout_seconds=stream_config.timeout,
        issue_number=attributed_issue,
        pr_number=attributed_pr,
        route=route,
    )
    stream_config = replace(
        stream_config,
        harness_env=harness_env,
        harness_transport=transport_provider,
        provider=harness_billing_provider(transport_provider, gate_model),
    )
    telemetry_cmd = (
        _telemetry_cmd(transport_provider, gate_tool, gate_model)
        if transport_provider == _GATEWAY
        else cmd
    )

    start = time.monotonic()
    transcript = ""
    success = False
    owned_runner: SubprocessRunner | None = None
    try:
        spawn_runner, owned_runner = _terminal_gateway_runner(
            stream_config.runner or get_default_runner(),
            config,
            transport_provider,
        )
        stream_config = replace(stream_config, runner=spawn_runner)
        transcript = await stream_claude_process(
            cmd=cmd,
            prompt=prompt,
            cwd=cwd,
            active_procs=active_procs,
            event_bus=event_bus,
            event_data=event_data,
            logger=logger,
            config=stream_config,
        )
        success = True
        return transcript
    finally:
        try:
            record_inference_telemetry(
                config,
                source=str(event_data.get("source", "unknown")),
                cmd=telemetry_cmd,
                prompt=prompt,
                transcript=transcript,
                duration_s=time.monotonic() - start,
                success=success,
                issue_number=attributed_issue,
                pr_number=attributed_pr,
                session_id=getattr(event_bus, "current_session_id", None),
                stats=stats,
                # The CLI produced the counts: Anthropic-shaped for the Claude
                # CLI even when the transport marker is ``gateway``/``zai``.
                usage_shape=usage_shape_for_tool(gate_tool),
            )
        finally:
            try:
                await revoke_gateway_key(harness_env)
            finally:
                if owned_runner is not None:
                    await owned_runner.cleanup()


# --- Pluggable one-shot LLM backends -----------------------------------------
# These live in THIS module (the gate + telemetry seam) on purpose: the raw
# spawns (CLI ``build_lightweight_command`` / OpenRouter ``httpx``) must sit
# inside the seam so ``run_lightweight_agent`` always gates the prompt first and
# records telemetry after. The agentic path (tools/multi-turn) stays on the
# Claude harness — Anthropic doesn't support routing it to non-Claude models.

_OPENROUTER = "openrouter"
_ZAI = "zai"
_KIMI = "kimi"
_GATEWAY = "gateway"


@dataclass(frozen=True)
class _OpenAICompatBackend:
    """A named OpenAI-compatible endpoint. Records where its (non-secret,
    UI-editable) base URL lives on the config, and which environment variables
    hold its (secret, environment-only) API key. Adding a backend is one entry
    in the registry below + a ``*_base_url`` field on the config + the provider
    name in the ``*_provider`` Literals (config.py)."""

    base_url_field: str
    api_key_envs: tuple[str, ...]

    def base_url(self, config: HydraFlowConfig) -> str:
        return getattr(config, self.base_url_field)

    def api_key(self) -> str:
        """The key, read straight from the environment. It is a secret, so it
        never lives on ``HydraFlowConfig`` (which can persist to config_file)
        and never appears in the settings UI — it stays in ``.env`` only."""
        for env in self.api_key_envs:
            value = os.environ.get(env, "")
            if value:
                return value
        return ""


# OpenAI-compatible one-shot backends: a direct HTTP POST to a
# ``{base_url}/chat/completions`` endpoint — no CLI, no tools, no agent loop.
# Both OpenRouter and z.ai speak this shape, so a role's dial can point at
# whichever the operator has credits for.
_OPENAI_COMPAT_BACKENDS: dict[str, _OpenAICompatBackend] = {
    _OPENROUTER: _OpenAICompatBackend(
        base_url_field="openrouter_base_url",
        api_key_envs=("OPENROUTER_API_KEY", "HYDRAFLOW_OPENROUTER_API_KEY"),
    ),
    _ZAI: _OpenAICompatBackend(
        base_url_field="zai_base_url",
        api_key_envs=("ZAI_API_KEY", "HYDRAFLOW_ZAI_API_KEY"),
    ),
    _KIMI: _OpenAICompatBackend(
        base_url_field="kimi_base_url",
        # MOONSHOT_API_KEY is Moonshot's own canonical env var; KIMI_API_KEY is a
        # friendlier alias, and HYDRAFLOW_KIMI_API_KEY mirrors the sibling prefix.
        api_key_envs=("MOONSHOT_API_KEY", "KIMI_API_KEY", "HYDRAFLOW_KIMI_API_KEY"),
    ),
}


def one_shot_provider_names() -> frozenset[str]:
    """Public, registry-derived names of direct one-shot HTTP providers."""

    return frozenset(_OPENAI_COMPAT_BACKENDS)


def provider_key_presence() -> dict[str, bool]:
    """Which OpenAI-compatible providers have their (secret) API key set in the
    environment — booleans ONLY, never the key value. Powers the settings UI's
    'key detected' badge so an operator can verify a backend is wired without
    opening ``.env`` or the secret ever leaving the process. Reuses each
    backend's own ``api_key()`` resolution, so the badge can never disagree with
    what a real spawn would actually find."""
    return {
        name: bool(backend.api_key())
        for name, backend in _OPENAI_COMPAT_BACKENDS.items()
    }


def normalize_provider(dial: str) -> str:
    """Map a per-role provider *dial* value to its billing-provider identity.

    The CLI-harness dial (``"claude"``) and anything unrecognized bill against
    Anthropic (``"anthropic"``); the OpenAI-compatible one-shot dials
    (``"openrouter"``/``"zai"``/``"kimi"``) are already their own billing
    identity and map to themselves. This is the single point that reconciles the
    config's ``*_provider`` Literal namespace (which spells the harness
    ``"claude"``) with ``CreditExhaustedError.provider`` (which spells it
    ``"anthropic"``), so the orchestrator can compare a signal's provider
    against each loop's routed backend."""
    if dial in _OPENAI_COMPAT_BACKENDS:
        return dial
    return PROVIDER_ANTHROPIC


def harness_billing_provider(provider: str, model: str) -> str:
    """Resolve a harness *transport* to its upstream billing identity.

    ``gateway`` is deliberately not a billing provider.  Its virtual key is
    bound to z.ai for GLM models and Anthropic for every other Claude-harness
    model.  Direct Claude/z.ai values are returned unchanged so their existing
    credit behavior is byte-for-byte stable.
    """

    if provider != _GATEWAY:
        return provider
    if model.strip().lower().startswith("glm"):
        return _ZAI
    return "claude"


def backend_probe_endpoint(provider: str, config: HydraFlowConfig) -> tuple[str, str]:
    """Resolve ``(base_url, api_key)`` for a one-shot backend's credit probe.

    Returns ``("", "")`` when *provider* is not a known OpenAI-compatible
    backend (e.g. ``"anthropic"``), which the probe treats as "cannot probe →
    fail-open". Reuses the registry's own ``base_url``/``api_key`` resolution so
    the probe hits exactly the endpoint + key a real spawn would use."""
    backend = _OPENAI_COMPAT_BACKENDS.get(provider)
    if backend is None:
        return "", ""
    # Key-split (#11267 review find): when the harness lane authenticates
    # with a DIFFERENT credential (the coding-plan key), corroborating a
    # non-authoritative cap against the REST key would falsely refute a
    # plan-quota exhaustion — probe healthy, signal discarded, retry storm
    # against the still-capped plan (the #9895/#10558 class). Probe the
    # lane the signal came from: non-authoritative (prose-scan) signals
    # originate from CLI spawns, which bill the HARNESS key; REST-lane
    # failures arrive as structured HTTP errors that parse authoritative
    # and never reach this probe.
    harness = _HARNESS_BACKENDS.get(provider)
    if harness is not None:
        harness_key = harness.api_key()
        if harness_key and harness_key != backend.api_key():
            return harness.base_url(config), harness_key
    return backend.base_url(config), backend.api_key()


# Anthropic-compatible *harness* backends: providers the Claude CLI can be
# pointed at via ANTHROPIC_BASE_URL so an agentic (tool-using) role runs on a
# non-Anthropic model. Distinct from _OPENAI_COMPAT_BACKENDS (the one-shot HTTP
# face) — z.ai appears in both, with a different URL for each. The gateway is a
# transport-only entry with dynamic per-spawn auth; kimi stays one-shot-only.
_HARNESS_BACKENDS: dict[str, _OpenAICompatBackend] = {
    _ZAI: _OpenAICompatBackend(
        base_url_field="zai_harness_base_url",
        # Two-key lane split: the agentic harness (Claude CLI ->
        # /api/anthropic) PREFERS the flat-rate GLM Coding Plan key, falling
        # back to the shared API-credits key. The one-shot REST lane
        # (_OPENAI_COMPAT_BACKENDS above) deliberately keeps ZAI_API_KEY
        # only — background-worker traffic stays on API credits, outside
        # the coding plan's prompts-per-window/concurrency quota.
        api_key_envs=(
            "ZAI_CODING_PLAN_KEY",
            "HYDRAFLOW_ZAI_CODING_PLAN_KEY",
            "ZAI_API_KEY",
            "HYDRAFLOW_ZAI_API_KEY",
        ),
    ),
    # Unlike direct harness backends, the gateway's credential is minted for
    # each spawn.  ``api_key_envs`` is intentionally empty: a virtual worker
    # token must never be read from ambient process state.
    _GATEWAY: _OpenAICompatBackend(
        base_url_field="gateway_base_url",
        api_key_envs=(),
    ),
}


def provider_api_key_envs() -> frozenset[str]:
    """Every environment variable name any registered backend — one-shot
    (``_OPENAI_COMPAT_BACKENDS``) or harness (``_HARNESS_BACKENDS``) — reads
    for its API key. The single source of truth for the provider-credential
    scrub surface: test fixtures union this in instead of hand-listing names,
    so an ambient developer/CI shell export (e.g. ``ZAI_CODING_PLAN_KEY``) of
    a bare, non-``HYDRAFLOW_``-prefixed provider key can't leak into a test
    session and silently defeat a ``*_without_zai_key``-style precondition."""
    return frozenset(
        env
        for backend in (*_OPENAI_COMPAT_BACKENDS.values(), *_HARNESS_BACKENDS.values())
        for env in backend.api_key_envs
    )


def harness_base_url(provider: str, config: HydraFlowConfig) -> str:
    """Anthropic-compatible base URL for a *harness* backend, or "" if none.

    Returns the endpoint the Claude CLI should be pointed at (via
    ``ANTHROPIC_BASE_URL``) when an agentic role's provider dial names a harness
    backend (``"zai"`` → ``/api/anthropic`` or ``"gateway"`` → the configured
    tap). Returns ``""`` for
    ``"claude"``/``"anthropic"`` (the native endpoint — no override) and for
    one-shot-only providers (``"openrouter"``/``"kimi"``), which never back an
    agentic harness."""
    backend = _HARNESS_BACKENDS.get(provider)
    if backend is None:
        return ""
    return backend.base_url(config)


async def resolve_harness_env(
    provider: str,
    config: HydraFlowConfig,
    *,
    model: str = "",
    source: str = "unknown",
    session_id: str | None = None,
    spawn_id: str | None = None,
    timeout_seconds: float | None = None,
    gateway_client: GatewayControlClient | None = None,
    issue_number: int | None = None,
    pr_number: int | None = None,
    route: EnforcedRoute | None = None,
) -> dict[str, str]:
    """Per-spawn env overrides that point the Claude CLI at a harness backend.

    Returns ``{}`` for ``"claude"``/``"anthropic"`` (the native endpoint — the
    main coding workers must get a pristine env) and for any non-harness
    provider. For the direct z.ai harness with its key present,
    returns ``ANTHROPIC_BASE_URL`` + ``ANTHROPIC_AUTH_TOKEN`` and clears
    ``ANTHROPIC_API_KEY`` so a host Claude key can't shadow the backend token.

    For ``gateway``, mints one short-lived virtual key for this spawn and binds
    it to the upstream implied by *model*.  Mint failures raise
    :class:`GatewayMintError`; gateway routing is fail closed and can never fall
    through to an ambient real provider credential. The returned mapping owns
    the retained key ID/expiry/control lease; production callers must pass it to
    :func:`revoke_gateway_key` from a ``finally`` block.

    CRITICAL: this MUST be merged into a per-spawn env, never exported globally —
    a global ``ANTHROPIC_BASE_URL`` would silently reroute every Claude worker to
    the backend. When the *direct z.ai* backend is selected but its key is unset,
    we retain its historical fall-open behavior. Gateway selection never falls
    open: mint/config failures raise before any worker process starts.
    """
    base_url = harness_base_url(provider, config)
    if provider == _GATEWAY and not base_url:
        # The docstring's "gateway selection never falls open" promise, held.
        # ``gateway_base_url`` declares ``min_length=1``, but the env-override
        # table assigns after construction, so an empty override reaches here —
        # and returning {} would spawn the policy-chosen model against whatever
        # ambient credential the host happens to have.
        raise GatewayMintError("gateway selected but gateway_base_url is unset")
    if not base_url:
        return {}
    if provider == _GATEWAY:
        control_token = os.environ.get("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", "").strip()
        if not control_token:
            raise GatewayMintError(
                "gateway selected but HYDRAFLOW_GATEWAY_CONTROL_TOKEN is unset"
            )
        resolved_spawn_id = spawn_id or uuid.uuid4().hex
        repo_class = cast(
            Literal["hydraflow", "client", "personal"],
            getattr(config, "gateway_repo_class", "personal"),
        )
        request: GatewayMintRequest | GatewayMintV2Request
        if route is not None:
            # ADR-0141: a governed spawn states identity and intent. It does not
            # name a provider binding, and there is no field on this request that
            # could carry one.
            request = GatewayMintV2Request(
                mint_attempt_id=route.mint_attempt_id,
                dispatch_id=route.dispatch_id,
                principal_kind="spawn",
                principal_id=source.strip() or "unknown",
                spawn_id=resolved_spawn_id,
                session_id=session_id,
                repo=str(getattr(config, "repo", "") or ""),
                repo_slug=str(getattr(config, "repo_slug", "") or "unknown"),
                repo_class=repo_class,
                worker_role=(
                    None if route.worker_role is None else route.worker_role.value
                ),
                request_face=route.context.request_face.value,
                requirement_kind=route.requirement.kind.value,
                requirement_value=route.requirement.value,
                requested_model=route.requested_model,
                effective_model=route.effective_model,
                route_decision_id=route.decision.decision_id,
                policy_id=route.decision.policy_id,
                policy_revision=route.decision.policy_revision,
                snapshot_hash=route.decision.snapshot_hash,
                capture_bodies=bool(getattr(config, "gateway_capture_bodies", False)),
                ttl_seconds=_gateway_ttl_seconds(config, timeout_seconds),
                issue_number=issue_number,
                pr_number=pr_number,
            )
        else:
            billing_provider = harness_billing_provider(provider, model)
            request = GatewayMintRequest(
                principal_kind="spawn",
                principal_id=source.strip() or "unknown",
                spawn_id=resolved_spawn_id,
                session_id=session_id,
                repo_slug=str(getattr(config, "repo_slug", "") or "unknown"),
                repo_class=repo_class,
                provider_binding=(
                    "zai-harness" if billing_provider == _ZAI else "anthropic"
                ),
                capture_bodies=bool(getattr(config, "gateway_capture_bodies", False)),
                ttl_seconds=_gateway_ttl_seconds(config, timeout_seconds),
                issue_number=issue_number,
                pr_number=pr_number,
            )
        client = gateway_client or _HttpGatewayControlClient()
        credential = await client.mint_key(
            base_url=base_url,
            control_token=control_token,
            request=request,
        )
        _validate_gateway_credential(credential)
        lease = _GatewayKeyLease(
            base_url=base_url,
            control_token=control_token,
            request=request,
            client=client,
            credential=credential,
        )
        return _RoutedHarnessEnv(
            {
                "ANTHROPIC_BASE_URL": base_url,
                "ANTHROPIC_AUTH_TOKEN": credential.token,
                "ANTHROPIC_API_KEY": "",
            },
            transport=_GATEWAY,
            gateway_lease=lease,
        )
    api_key = _HARNESS_BACKENDS[provider].api_key()
    if not api_key:
        logger.warning(
            "harness backend %r selected but its API key is unset; falling back "
            "to the native Anthropic endpoint",
            provider,
        )
        return {}
    return {
        "ANTHROPIC_BASE_URL": base_url,
        "ANTHROPIC_AUTH_TOKEN": api_key,
        "ANTHROPIC_API_KEY": "",
    }


def _telemetry_cmd(provider: str, tool: str, model: str) -> list[str]:
    """The ``cmd``-shaped descriptor ``record_inference_telemetry`` parses into
    ``(tool, model)``. For an OpenAI-compatible backend the 'tool' is the
    provider name (``openrouter`` / ``zai``) so the cost dashboard attributes
    each backend distinctly from the CLI tools. Gateway-routed CLI calls use
    ``gateway`` so coverage can exclude their duplicate prompt-telemetry row."""
    head = telemetry_tool_for_transport(provider, tool)
    return [head, "--model", model]


def telemetry_tool_for_transport(provider: str, tool: str) -> str:
    """Return the telemetry tool marker without losing model attribution."""
    if provider in _OPENAI_COMPAT_BACKENDS or provider == _GATEWAY:
        return provider
    return tool


def _terminal_gateway_runner(
    runner: SubprocessRunner,
    config: HydraFlowConfig,
    transport_provider: str,
) -> tuple[SubprocessRunner, SubprocessRunner | None]:
    """Replace a host runner with an owned isolated runner at terminal state."""

    if transport_provider != _GATEWAY or not config.gateway_fleet_ratchet_enabled:
        return runner, None

    if not isinstance(runner, HostRunner):
        return runner, None

    isolated = get_docker_runner(config)
    if isinstance(isolated, HostRunner):
        raise RuntimeError(
            "terminal gateway profile could not establish Docker isolation"
        )
    return isolated, isolated


async def _claude_cli_complete(
    *,
    runner: SubprocessRunner,
    tool: str,
    model: str,
    prompt: str,
    timeout: float,
    gh_token: str,
    isolate_user_settings: bool,
    provider: str = "claude",
    config: HydraFlowConfig | None = None,
    source: str = "unknown",
    session_id: str | None = None,
    gateway_client: GatewayControlClient | None = None,
    usage_out: dict[str, object] | None = None,
    route: EnforcedRoute | None = None,
) -> SimpleResult:
    """The Claude CLI backend (today's behaviour). Credit-out surfaces as
    ``rc != 0`` output text, so it is detected and raised here.

    *provider* selects the harness backend: ``"claude"`` runs the native
    Anthropic endpoint; ``"zai"`` points the CLI at GLM's Anthropic-compatible
    endpoint via a per-spawn env override (needs *config* for the URL). The
    credit-out is tagged with the resolved provider so a backend cap is scoped
    to loops on that backend.

    The spawn requests the CLI's JSON result envelope; it is unwrapped here so
    ``SimpleResult.stdout`` is the bare reply text callers always parsed, and
    the envelope's token usage is copied into *usage_out* (the
    ``StreamParser.usage_snapshot`` shape) for the telemetry row."""

    from agent_cli import AgentTool, build_lightweight_command  # noqa: PLC0415

    cmd, cmd_input = build_lightweight_command(
        tool=cast(AgentTool, tool),
        model=model,
        prompt=prompt,
        isolate_user_settings=isolate_user_settings,
    )
    env = make_clean_env(gh_token)
    harness_env: dict[str, str] = {}
    try:
        if config is not None:
            harness_env = await resolve_harness_env(
                provider,
                config,
                model=model,
                source=source,
                session_id=session_id,
                timeout_seconds=timeout,
                gateway_client=gateway_client,
                route=route,
            )
            if provider == _GATEWAY:
                env = scrub_gateway_spawn_env(env)
            env.update(harness_env)
        result = await runner.run_simple(cmd, env=env, input=cmd_input, timeout=timeout)
        result = _unwrap_result_envelope(result, usage_out)
        raise_if_credit_exhausted(
            result.stdout,
            result.stderr,
            tool,
            provider=harness_billing_provider(provider, model),
        )
        return result
    finally:
        await revoke_gateway_key(harness_env)


def _unwrap_result_envelope(
    result: SimpleResult, usage_out: dict[str, object] | None
) -> SimpleResult:
    """Collapse a ``--output-format json`` envelope to reply text + usage.

    Non-envelope stdout (bare text, the caller's own JSON reply, MockWorld's
    stream-json event lines) is returned untouched. An ``is_error`` envelope
    on a zero exit is surfaced as a failed result — the CLI can exit 0 after a
    mid-run API error or a max-turns stop, and callers branch on
    ``returncode`` — while keeping the usage it reports, so the spend is
    still recorded.
    """
    envelope = parse_result_envelope(result.stdout)
    if envelope is None:
        return result
    if usage_out is not None:
        usage_out.update(envelope.usage)
    returncode = result.returncode
    stderr = result.stderr
    if envelope.is_error and returncode == 0:
        returncode = 1
        stderr = stderr or envelope.result
    return SimpleResult(stdout=envelope.result, stderr=stderr, returncode=returncode)


async def _openai_compatible_complete(
    *,
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    timeout: float,
    response_schema: dict[str, object] | None = None,
    usage_out: dict[str, object] | None = None,
) -> SimpleResult:
    """Direct OpenAI-compatible completion (OpenRouter, z.ai, …). One HTTP POST;
    no tools, no agent loop. ``response_schema`` switches on native strict-JSON
    output (more reliable than parsing JSON out of prose). HTTP 429/402 and
    quota/credit error bodies raise :class:`CreditExhaustedError` so the
    orchestrator's pause/refund fires. ``provider`` only labels errors."""

    from execution import SimpleResult  # noqa: PLC0415
    from subprocess_util import (  # noqa: PLC0415
        CreditExhaustedError,
        is_credit_exhaustion,
    )

    if not api_key:
        return SimpleResult(stderr=f"{provider}: API key is not set", returncode=-1)

    payload: dict[str, object] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if response_schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "response",
                "strict": True,
                "schema": response_schema,
            },
        }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            )
    except httpx.TimeoutException as exc:
        raise TimeoutError(str(exc)) from exc

    if resp.status_code in (402, 429):
        # Tag the signal with THIS backend so the orchestrator scopes the pause
        # to loops routed here — a z.ai/kimi cap must not halt Claude work, and
        # vice-versa (#9807).
        # A structured HTTP 402/429 from the backend is ground truth, not quoted
        # prose — authoritative so the orchestrator pauses without a probe (#10558).
        raise CreditExhaustedError(
            f"{provider} {resp.status_code}: {resp.text[:200]}",
            provider=provider,
            authoritative=True,
        )
    if resp.status_code >= 400:
        body = resp.text or ""
        if is_credit_exhaustion(body):
            raise CreditExhaustedError(
                f"{provider}: {body[:200]}", provider=provider, authoritative=True
            )
        return SimpleResult(
            stderr=f"{provider} http {resp.status_code}: {body[:300]}",
            returncode=resp.status_code,
        )
    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"] or ""
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        return SimpleResult(
            stderr=f"{provider}: malformed response ({exc})", returncode=-1
        )
    # Surface the API's real token usage so telemetry records actual cost
    # (token_source="actual") instead of the CLI path's char estimate.
    if usage_out is not None:
        u = data.get("usage") or {}
        usage_out["input_tokens"] = int(u.get("prompt_tokens", 0) or 0)
        usage_out["output_tokens"] = int(u.get("completion_tokens", 0) or 0)
        usage_out["total_tokens"] = int(u.get("total_tokens", 0) or 0)
        usage_out["usage_available"] = bool(u.get("total_tokens"))
    return SimpleResult(stdout=content, returncode=0)


async def run_lightweight_agent(
    *,
    runner: SubprocessRunner,
    config: HydraFlowConfig,
    tool: AgentTool,
    model: str,
    prompt: str,
    source: str,
    timeout: float,
    gh_token: str = "",
    issue_number: int | None = None,
    pr_number: int | None = None,
    session_id: str | None = None,
    isolate_user_settings: bool = True,
    issue_labels: Sequence[str] = (),
    provider: str | None = None,
    response_schema: dict[str, object] | None = None,
    gateway_client: GatewayControlClient | None = None,
    spawn_out: dict[str, object] | None = None,
) -> SimpleResult:
    """One-shot lightweight LLM call with credit detection + telemetry.

    *provider* selects the backend. An omitted provider inherits
    ``config.maintenance_provider``; callers with a dedicated role dial pass it
    explicitly and therefore take precedence. The resolved backend is either
    ``"claude"`` (the CLI harness), ``"gateway"``, or a direct
    OpenAI-compatible HTTP provider such as ``"openrouter"`` or ``"zai"``.
    All return the same ``SimpleResult`` and own their own credit-exhaustion
    detection, so the credit + telemetry contract below holds regardless of
    backend.
    *response_schema*, when given, drives native strict-JSON output on the
    OpenAI-compatible path (the CLI path uses prompt-based JSON).

    Centralizes the credit + telemetry contract for the non-streaming
    ``run_simple`` spawn path so callers don't reinvent it:

    * Raises :class:`CreditExhaustedError` when the CLI signals credit
      exhaustion via an exception OR via stdout/stderr text. ``run_simple``
      surfaces credit-out as ``rc != 0`` text, never as an exception, so a
      manual scan is required — ``reraise_on_credit_or_bug`` alone is a no-op
      on this path.
    * ``reraise_on_credit_or_bug`` propagates likely-bug exceptions
      (TypeError/KeyError/...); transient failures collapse to a
      ``SimpleResult(returncode=-1)`` the caller treats as a soft failure.
    * Records :class:`PromptTelemetry` (``source=``) so the spend is visible
      to the cost cap / ROI dashboard. Both backends report real token usage
      (the CLI via its JSON result envelope, the HTTP providers via the
      response ``usage``), so the row is token-accurate
      (``token_source="actual"``); a reply with no usage falls back to a char
      estimate.

    Returns the ``SimpleResult``; callers inspect ``returncode``/``stdout`` as
    before. Lightweight LLM spawns MUST route through this helper rather than
    calling ``run_simple`` on a ``build_lightweight_command`` directly.

    *isolate_user_settings* defaults to ``True``: every current lightweight
    caller (wiki compiler, ADR reviewer, transcript summarizer, PR unsticker,
    …) is a strict-output contract worker, so the spawn is restricted to
    ``project`` settings to keep a host user-level ``SessionStart`` hook from
    leaking skill-invocation guidance into the reply. Pass ``False`` for a
    lightweight spawn that legitimately needs host plugins/skills.

    *issue_labels* feeds the CH-6 gate's upward-only ``data-class:`` label
    elevation, mirroring :func:`stream_claude_with_telemetry`. Callers with
    an issue in scope MUST pass its labels (``issue.labels`` /
    ``issue.tags``); without them only the repo-declared class is enforced
    (``tests/test_prompt_gate_completeness.py`` pins every call site).

    *spawn_out*, when given, is filled with what this seam actually spawned:
    ``model`` (the model the child really ran on, **after** any enforcement
    rewrite), ``provider``, ``usage`` (real token counts when the backend
    reported them), and ``route_decision_id`` when a governed route bound the
    spawn. It exists because ``SimpleResult`` carries reply text and nothing
    else, and a caller that must *record* which model served a request — a
    brokered worker's receipt, #11541 — cannot honestly report the model it
    asked for. Purely additive: every existing caller omits it and nothing
    about the spawn changes.
    """
    from exception_classify import (  # noqa: PLC0415
        exc_detail,
        reraise_on_credit_or_bug,
    )
    from execution import SimpleResult  # noqa: PLC0415

    # CH-6 data-governance gate (#9734): redact/block BEFORE spawn. A block
    # collapses to this seam's soft-failure contract (rc=-1) — the prompt was
    # never sent (fail closed), the gate already wrote the audit record, and
    # no telemetry row is recorded because no inference happened.
    try:
        gated = gate_prompt(
            prompt,
            config=config,
            source=source,
            tool=tool,
            issue_number=issue_number,
            issue_labels=issue_labels,
        )
    except PromptGateBlockedError as exc:
        return SimpleResult(stderr=str(exc), returncode=-1)
    prompt = gated.prompt

    transport_provider = config.maintenance_provider if provider is None else provider
    if (
        getattr(config, "gateway_fleet_ratchet_enabled", False) is True
        and transport_provider == "claude"
        and tool == "claude"
    ):
        transport_provider = _GATEWAY
    if transport_provider == _GATEWAY and tool != "claude":
        msg = (
            f"provider 'gateway' requires the Claude harness, got tool {tool!r} "
            f"for source {source!r}"
        )
        raise ValueError(msg)
    # Backend selection (pluggable one-shot provider). The chosen backend owns
    # its own credit-exhaustion detection (CLI: output text; OpenRouter: HTTP
    # 429/402). Both spawns live in THIS seam module so the CH-6 gate (above)
    # and the telemetry record (below) always wrap them. ``cmd`` is only a
    # telemetry descriptor parsed into (tool, model).
    cmd = _telemetry_cmd(transport_provider, tool, model)
    # Routing shadow (#11536, ADR-0139): this is the seam the per-role
    # ``*_provider`` dials run through, so it is where a z.ai-pinned loop
    # becomes observable. Observation only — the transport is already resolved.
    from hydraflow_gateway.routing_policy import RequestFace
    from route_enforcement import (
        EnforcementRefused,
        canary_armed,
        enforce_canary_route,
    )
    from route_shadow import dialled_route_stages, record_dialled_route_shadow

    await asyncio.to_thread(
        record_dialled_route_shadow,
        config=config,
        principal_id=source,
        requested_provider=provider,
        transport_provider=transport_provider,
        model=model,
        request_face=RequestFace.ONE_SHOT,
        issue_number=issue_number,
        pr_number=pr_number,
    )
    # Enforcement canary (#11539, ADR-0141): None unless this is the armed
    # repository AND ``transport_provider`` is the gateway, so a direct
    # OpenAI-compatible backend — which the gateway never sees — is untouched.
    # Here the model is a plain variable rather than an argv, so the rewrite is
    # an assignment; ``cmd`` is only a telemetry descriptor and is rebuilt from
    # it so the recorded model is the one that actually ran.
    route = None
    try:
        if canary_armed(config):
            route = await asyncio.to_thread(
                enforce_canary_route,
                config=config,
                principal_id=source,
                stages=dialled_route_stages(
                    config=config,
                    requested_provider=provider,
                    transport_provider=transport_provider,
                ),
                final_provider=transport_provider,
                final_model=model,
                request_face=RequestFace.ONE_SHOT,
            )
    except EnforcementRefused as exc:
        # Collapses to this seam's soft-failure contract, exactly like the CH-6
        # gate block above and for the same reason: the prompt was never sent
        # (fail closed), and no telemetry row is recorded because no inference
        # happened. A caretaker loop reads rc=-1 and tries again later, which is
        # right — a held route is a state an operator can change.
        return SimpleResult(stderr=str(exc), returncode=-1)
    if route is not None:
        model = route.effective_model
        cmd = _telemetry_cmd(transport_provider, tool, model)
    # Only now, past every early return: ``_terminal_gateway_runner`` may open a
    # Docker API client, and the one path that returns between here and the
    # ``finally`` that closes it would leak one per refused attempt — and a held
    # route is a persistent state a caretaker loop retries.
    runner, owned_runner = _terminal_gateway_runner(
        runner,
        config,
        transport_provider,
    )
    start = time.monotonic()
    success = False
    record_row = False
    result = SimpleResult(returncode=-1)
    # Real token usage, filled by whichever backend runs: the HTTP providers
    # copy the response ``usage`` in; the CLI path unwraps its JSON result
    # envelope. Stays empty (-> char estimate) when the spawn never answered.
    usage_stats: dict[str, object] = {}
    backend = _OPENAI_COMPAT_BACKENDS.get(transport_provider)
    try:
        try:
            if backend is not None:
                result = await _openai_compatible_complete(
                    provider=transport_provider,
                    base_url=backend.base_url(config),
                    api_key=backend.api_key(),
                    model=model,
                    prompt=prompt,
                    timeout=timeout,
                    response_schema=response_schema,
                    usage_out=usage_stats,
                )
            else:
                result = await _claude_cli_complete(
                    runner=runner,
                    tool=tool,
                    model=model,
                    prompt=prompt,
                    timeout=timeout,
                    gh_token=gh_token,
                    isolate_user_settings=isolate_user_settings,
                    provider=transport_provider,
                    config=config,
                    source=source,
                    session_id=session_id,
                    gateway_client=gateway_client,
                    usage_out=usage_stats,
                    route=route,
                )
        except TimeoutError:
            # ``asyncio.wait_for`` raises a *bare* TimeoutError whose ``str()``
            # is "", which would collapse to an undiagnosable "rc=-1: " at the
            # caller's failure log (the symptom that surfaced the masked wiki
            # compilation timeouts). Spell out the deadline so the soft failure
            # is actionable; a timeout is transient, so it is recorded as a
            # failed inference like any other soft rc=-1.
            result = SimpleResult(
                stderr=f"timed out after {timeout:.0f}s", returncode=-1
            )
            record_row = True
            return result
        except Exception as exc:
            # Credit / likely-bug exceptions propagate so the outer loop can
            # pause or surface the bug — and are NOT recorded, matching
            # BaseSubprocessRunner (which reraises before its telemetry write)
            # so a credit-blocked spawn never attributes phantom cost. Transient
            # failures become a soft rc=-1 result the caller treats as an empty
            # reply, and ARE recorded as a failed inference. ``exc_detail`` keeps
            # a diagnostic even when ``str(exc)`` is empty (bare OSError, etc.).
            reraise_on_credit_or_bug(exc)
            result = SimpleResult(stderr=exc_detail(exc), returncode=-1)
            record_row = True
            return result
        success = result.returncode == 0
        record_row = True
        return result
    finally:
        try:
            if spawn_out is not None:
                # Filled in the ``finally`` so it is populated on every exit —
                # including the timeout and soft-failure returns above, where a
                # caller minting a receipt still has to say which model it was
                # that failed.
                spawn_out.update(
                    {
                        "model": model,
                        "provider": transport_provider,
                        "usage": dict(usage_stats),
                        "route_decision_id": (
                            "" if route is None else route.decision.decision_id
                        ),
                    }
                )
            if record_row:
                record_inference_telemetry(
                    config,
                    source=source,
                    cmd=cmd,
                    prompt=prompt,
                    transcript=result.stdout or "",
                    duration_s=time.monotonic() - start,
                    success=success,
                    issue_number=issue_number,
                    pr_number=pr_number,
                    session_id=session_id,
                    usage_shape=(
                        USAGE_SHAPE_OPENAI_COMPAT
                        if backend is not None
                        else usage_shape_for_tool(tool)
                    ),
                    stats=usage_stats,
                )
        finally:
            if owned_runner is not None:
                await owned_runner.cleanup()
