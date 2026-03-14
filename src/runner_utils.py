"""Shared subprocess streaming utilities for agent runners."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
from collections.abc import Callable
from pathlib import Path

from events import EventBus, EventType, HydraFlowEvent
from execution import SubprocessRunner, get_default_runner
from models import TranscriptEventData, TranscriptLinePayload
from stream_parser import StreamParser
from subprocess_util import (
    CreditExhaustedError,
    is_credit_exhaustion,
    make_clean_env,
    parse_credit_resume_time,
)

logger = logging.getLogger("hydraflow.runner_utils")


class AuthenticationRetryError(RuntimeError):
    """Raised when the agent CLI reports authentication_failed.

    Treated as retryable — OAuth token refresh can fail transiently.
    """


def prepare_command(cmd: list[str], prompt: str) -> tuple[list[str], bool]:
    """Prepare the subprocess command and determine stdin mode.

    Returns ``(cmd_to_run, use_prompt_arg)`` where *use_prompt_arg* is ``True``
    when the prompt is embedded in the command rather than piped via stdin.
    """
    use_codex_exec = len(cmd) >= 2 and cmd[0] == "codex" and cmd[1] == "exec"
    use_pi_print = bool(cmd) and cmd[0] == "pi" and ("-p" in cmd or "--print" in cmd)
    use_claude_print = bool(cmd) and cmd[0] == "claude" and "-p" in cmd
    use_prompt_arg = use_codex_exec or use_pi_print or use_claude_print
    if use_prompt_arg:
        if use_claude_print or use_pi_print:
            # Claude/Pi CLI require the prompt immediately after -p/--print;
            # placing it at the end causes "Input must be provided" errors.
            flag = "-p" if "-p" in cmd else "--print"
            idx = cmd.index(flag)
            cmd_to_run = [*cmd[: idx + 1], prompt, *cmd[idx + 1 :]]
        else:
            # Codex exec: prompt is a trailing positional argument.
            cmd_to_run = [*cmd, prompt]
    else:
        cmd_to_run = cmd
    return cmd_to_run, use_prompt_arg


def validate_post_stream(
    *,
    raw_lines: list[str],
    stderr_text: str,
    accumulated_text: str,
    result_text: str,
    early_killed: bool,
    returncode: int | None,
    parser: StreamParser,
    logger: logging.Logger,
    usage_stats: dict[str, object] | None,
) -> str:
    """Run post-stream checks and build the transcript string.

    Raises :class:`AuthenticationRetryError` or :class:`CreditExhaustedError`
    when the corresponding conditions are detected.
    """
    if not early_killed and returncode != 0:
        logger.warning(
            "Process exited with code %d: %s",
            returncode,
            stderr_text[:500],
        )

    # Detect authentication failures from stream-json output.
    raw_output = "\n".join(raw_lines)
    if not early_killed and "authentication_failed" in raw_output:
        raise AuthenticationRetryError(
            "Agent CLI authentication failed — check "
            "ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN"
        )

    # Check for credit exhaustion in both stderr and transcript.
    combined = f"{stderr_text}\n{accumulated_text}"
    if not early_killed and is_credit_exhaustion(combined):
        resume_at = parse_credit_resume_time(combined)
        raise CreditExhaustedError("API credit limit reached", resume_at=resume_at)

    if usage_stats is not None:
        usage_stats.update(parser.usage_snapshot)

    transcript = result_text or accumulated_text.rstrip("\n") or "\n".join(raw_lines)

    # Log stderr when transcript is empty — this is the only place
    # stderr content is available and it's critical for diagnosing
    # silent subprocess failures (e.g. CLI auth errors, missing flags).
    if not transcript.strip() and stderr_text:
        logger.warning(
            "Process produced empty stdout (rc=%d), stderr: %s",
            returncode or 0,
            stderr_text[:500],
        )

    return transcript


async def create_agent_process(
    *,
    cmd: list[str],
    prompt: str,
    cwd: Path,
    runner: SubprocessRunner,
    gh_token: str = "",
) -> tuple[asyncio.subprocess.Process, bool]:
    """Create and return an agent subprocess.

    Returns ``(process, use_prompt_arg)`` where *use_prompt_arg* indicates
    whether the prompt was embedded in the command (vs. piped via stdin).
    """
    env = make_clean_env(gh_token)
    cmd_to_run, use_prompt_arg = prepare_command(cmd, prompt)
    stdin_mode = (
        asyncio.subprocess.DEVNULL if use_prompt_arg else asyncio.subprocess.PIPE
    )

    proc = await runner.create_streaming_process(
        cmd_to_run,
        cwd=str(cwd),
        env=env,
        stdin=stdin_mode,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=1024 * 1024,  # 1 MB — stream-json lines can exceed 64 KB default
        start_new_session=True,  # Own process group for reliable cleanup
    )
    return proc, use_prompt_arg


async def feed_stdin(proc: asyncio.subprocess.Process, prompt: str) -> None:
    """Write *prompt* to the process's stdin and close."""
    assert proc.stdin is not None
    proc.stdin.write(prompt.encode())
    await proc.stdin.drain()
    proc.stdin.close()


async def read_and_publish_stream(
    *,
    proc: asyncio.subprocess.Process,
    stderr_task: asyncio.Task[bytes],
    event_bus: EventBus,
    event_data: TranscriptEventData,
    on_output: Callable[[str], bool] | None = None,
    usage_stats: dict[str, object] | None = None,
    logger: logging.Logger,
) -> str:
    """Read stdout lines, publish events, and return the transcript.

    Handles early termination via *on_output* callback and runs
    post-stream validation.
    """
    assert proc.stdout is not None
    stdout_stream = proc.stdout

    parser = StreamParser()
    raw_lines: list[str] = []
    result_text = ""
    accumulated_text = ""
    early_killed = False

    async for raw in stdout_stream:
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
                HydraFlowEvent(
                    type=EventType.TRANSCRIPT_LINE,
                    data=line_data,
                )
            )

        if on_output is not None and not early_killed and on_output(accumulated_text):
            early_killed = True
            proc.kill()
            break

    stderr_bytes = await stderr_task
    await proc.wait()
    stderr_text = stderr_bytes.decode(errors="replace").strip()

    return validate_post_stream(
        raw_lines=raw_lines,
        stderr_text=stderr_text,
        accumulated_text=accumulated_text,
        result_text=result_text,
        early_killed=early_killed,
        returncode=proc.returncode,
        parser=parser,
        logger=logger,
        usage_stats=usage_stats,
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
    on_output: Callable[[str], bool] | None = None,
    timeout: float = 3600.0,
    runner: SubprocessRunner | None = None,
    usage_stats: dict[str, object] | None = None,
    gh_token: str = "",
) -> str:
    """Run an agent subprocess and stream its output.

    Returns the transcript string, using the fallback chain:
    result_text → accumulated_text → raw_lines.
    """
    if runner is None:
        runner = get_default_runner()

    proc, use_prompt_arg = await create_agent_process(
        cmd=cmd,
        prompt=prompt,
        cwd=cwd,
        runner=runner,
        gh_token=gh_token,
    )
    active_procs.add(proc)

    stderr_task: asyncio.Task[bytes] | None = None
    try:
        assert proc.stdout is not None
        assert proc.stderr is not None

        if not use_prompt_arg:
            await feed_stdin(proc, prompt)

        stderr_task = asyncio.create_task(proc.stderr.read())

        async def _body() -> str:
            return await read_and_publish_stream(
                proc=proc,
                stderr_task=stderr_task,
                event_bus=event_bus,
                event_data=event_data,
                on_output=on_output,
                usage_stats=usage_stats,
                logger=logger,
            )

        return await asyncio.wait_for(_body(), timeout=timeout)
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"Agent process timed out after {timeout}s") from exc
    except asyncio.CancelledError:
        proc.kill()
        raise
    finally:
        if stderr_task is not None and not stderr_task.done():
            stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)
        active_procs.discard(proc)


def terminate_processes(active_procs: set[asyncio.subprocess.Process]) -> None:
    """Kill all processes in *active_procs* and their process groups."""
    for proc in list(active_procs):
        with contextlib.suppress(ProcessLookupError, OSError):
            if proc.pid is not None:
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
