"""Shared async subprocess helper for HydraFlow."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from circuit_breaker import CircuitBreaker
    from execution import SubprocessRunner

logger = logging.getLogger("hydraflow.subprocess")

# ---------------------------------------------------------------------------
# Shadow sampling hook (#8786 Phase 0.2)
#
# When a sampler is installed via :func:`set_shadow_sampler`, every
# completed ``gh`` / ``git`` / ``docker`` / ``claude`` call feeds it the
# (adapter, command, args, stdout, stderr, exit_code) tuple. Sampler
# failures are caught and logged — they MUST NOT break the production
# call path. Default is None (no sampling).
# ---------------------------------------------------------------------------
_ShadowSampler = Callable[..., object]
_shadow_sampler: _ShadowSampler | None = None

_ADAPTER_BY_COMMAND: dict[str, str] = {
    "gh": "github",
    "git": "git",
    "docker": "docker",
    "claude": "claude",
}


def set_shadow_sampler(sampler: _ShadowSampler | None) -> None:
    """Install (or clear with None) the shadow-corpus sampling hook.

    The sampler is invoked with keyword args
    ``adapter, command, args, stdout, stderr, exit_code`` after every
    completed call to ``gh``/``git``/``docker``/``claude``. Non-adapter
    binaries (npm, ruff, …) are skipped. The sampler runs synchronously
    inside ``run_subprocess`` but exceptions are swallowed — observability
    must never break the production call path.
    """
    global _shadow_sampler  # noqa: PLW0603
    _shadow_sampler = sampler


def _maybe_sample_shadow(
    cmd: tuple[str, ...], exit_code: int, stdout: str, stderr: str
) -> None:
    """Fire the shadow sampler (if installed) for known adapter commands."""
    if _shadow_sampler is None or not cmd:
        return
    adapter = _ADAPTER_BY_COMMAND.get(cmd[0])
    if adapter is None:
        return
    try:
        _shadow_sampler(
            adapter=adapter,
            command=cmd[0],
            args=list(cmd[1:]),
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
        )
    except Exception:  # noqa: BLE001 — observability must never break the call path
        logger.warning("shadow sampler raised; ignoring", exc_info=True)


# ---------------------------------------------------------------------------
# Pluggable time source — allows tests to inject FakeClock without patching
# stdlib. Production code always uses time.time. Only the rate-limit cooldown
# logic calls _time_source(); all other timing calls are left untouched.
# ---------------------------------------------------------------------------
_time_source: Callable[[], float] = time.time


def set_time_source(fn: Callable[[], float]) -> None:
    """Override the module-level time source (for tests only)."""
    global _time_source  # noqa: PLW0603
    _time_source = fn


def reset_time_source() -> None:
    """Restore the default ``time.time`` time source."""
    global _time_source  # noqa: PLW0603
    _time_source = time.time


def _get_time_source() -> Callable[[], float]:
    return _time_source


# Global semaphore to limit concurrent gh/git subprocess calls and prevent
# GitHub API rate limiting when multiple async loops poll simultaneously.
_gh_semaphore: asyncio.Semaphore | None = None
_GH_DEFAULT_CONCURRENCY = 5

# Global rate-limit cooldown: when ANY call gets a 403 rate limit,
# ALL callers pause until this timestamp (UTC).
_rate_limit_until: datetime | None = None
_RATE_LIMIT_COOLDOWN_SECONDS = 60
_RATE_LIMIT_MAX_COOLDOWN_SECONDS = 480
_rate_limit_current_cooldown: int = _RATE_LIMIT_COOLDOWN_SECONDS
# Polling interval for _wait_for_rate_limit_cooldown so it re-reads the
# deadline each tick rather than sleeping for the full remaining duration.
_RATE_LIMIT_POLL_INTERVAL: float = 1.0
# Guards all read-modify-write operations on _rate_limit_current_cooldown
# and _rate_limit_until so concurrent callers cannot corrupt the backoff.
_rate_limit_lock: threading.Lock = threading.Lock()

# Global circuit breaker for the gh/git subprocess boundary. Opens after
# ``max_failures`` consecutive non-rate-limit failures (GitHub/network down) so
# callers fail fast instead of hammering a dead API; it auto-probes (HALF_OPEN)
# after ``reset_timeout`` so it can never halt the factory permanently. When
# disabled, every call is allowed — the live kill-switch, toggled via
# ``PATCH /api/config`` → ``set_gh_circuit_breaker_enabled``. The breaker's
# methods are synchronous and never await, so the single asyncio loop runs each
# atomically; no extra lock is needed (unlike the cross-thread rate-limit state).
_gh_circuit_breaker: CircuitBreaker | None = None
_gh_circuit_breaker_enabled: bool = False


def configure_gh_circuit_breaker(
    enabled: bool, max_failures: int = 10, reset_timeout: float = 60.0
) -> None:
    """Configure the gh/git circuit breaker. Call once during startup."""
    global _gh_circuit_breaker, _gh_circuit_breaker_enabled  # noqa: PLW0603
    from circuit_breaker import CircuitBreaker  # noqa: PLC0415

    _gh_circuit_breaker = CircuitBreaker(
        "gh-subprocess", max_failures=max_failures, reset_timeout=reset_timeout
    )
    _gh_circuit_breaker_enabled = enabled
    logger.info(
        "gh circuit breaker configured (enabled=%s, max_failures=%d, "
        "reset_timeout=%.0fs)",
        enabled,
        max_failures,
        reset_timeout,
    )


def set_gh_circuit_breaker_enabled(enabled: bool) -> None:
    """Enable/disable the gh circuit breaker at runtime — the live kill-switch.

    Toggled via ``PATCH /api/config`` (``gh_circuit_breaker_enabled``) so an
    operator can disable a misbehaving breaker without a restart. When disabled
    the breaker never blocks a call (outcomes are simply not consulted).
    """
    global _gh_circuit_breaker_enabled  # noqa: PLW0603
    _gh_circuit_breaker_enabled = enabled
    logger.info("gh circuit breaker enabled=%s (runtime toggle)", enabled)


def configure_gh_concurrency(limit: int) -> None:
    """Set the global GitHub API concurrency limit.

    Must be called once during startup before any subprocess calls.
    """
    global _gh_semaphore  # noqa: PLW0603
    _gh_semaphore = asyncio.Semaphore(limit)
    logger.info("GitHub API concurrency limit set to %d", limit)


def _get_gh_semaphore() -> asyncio.Semaphore:
    """Return the global semaphore, creating with defaults if not configured.

    The None-check + construct + assign sequence is guarded by
    ``_rate_limit_lock`` so two threads racing the lazy init can't each
    construct a fresh ``Semaphore`` and silently overwrite each other
    (issue #8657 — same TOCTOU anti-pattern as #7838 and #7839).
    """
    global _gh_semaphore  # noqa: PLW0603
    if _gh_semaphore is None:
        with _rate_limit_lock:
            if _gh_semaphore is None:
                _gh_semaphore = asyncio.Semaphore(_GH_DEFAULT_CONCURRENCY)
    return _gh_semaphore


def _is_rate_limited(stderr: str) -> bool:
    """Check if stderr indicates a GitHub API rate limit (HTTP 403 or 429).

    GitHub signals rate limiting two ways: HTTP 403 for the secondary/abuse
    limit ("You have exceeded a secondary rate limit") and HTTP 429 for the
    primary limit. Both must route to the global cooldown in ``run_subprocess``
    rather than the per-call retry path — a 429 that slips through would either
    fail outright (429 is not in ``_RETRYABLE_PATTERNS``) or retry too fast,
    amplifying the limit across concurrent agents instead of pausing.
    """
    lower = stderr.lower()
    if "rate limit" not in lower:
        return False
    return any(code in lower for code in ("403", "http 403", "429", "http 429"))


# Infrastructure/outage failure signatures — GitHub or the network is unhealthy.
# ONLY these count toward the circuit breaker. A 4xx (404 "not found", 422,
# "label does not exist", "cannot approve your own pull request", etc.) means
# GitHub is UP and answered with a client error — that's normal control flow,
# not an outage, and must never trip the process-global breaker.
_GH_OUTAGE_PATTERNS = (
    "http 5",  # any 5xx
    "internal server error",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
    "could not resolve",
    "could not connect",
    "connection refused",
    "connection reset",
    "network is unreachable",
    "timed out",
    "timeout",
    "i/o timeout",
    "tls handshake",
)


def _is_gh_outage_error(stderr: str) -> bool:
    """True when a failed gh call looks like a GitHub/network outage.

    Used to decide whether a failure counts toward the circuit breaker. Client
    errors (4xx) and business-logic non-zero exits are excluded — they are not
    outage signals, so they must not accumulate toward an OPEN that would halt
    all gh calls factory-wide.
    """
    low = stderr.lower()
    return any(p in low for p in _GH_OUTAGE_PATTERNS)


def _trigger_rate_limit_cooldown() -> None:
    """Set the global cooldown so all callers pause.

    Uses exponential backoff: starts at 60s, doubles on each consecutive
    rate-limit hit, caps at 480s. Resets to 60s on a successful call
    (see :func:`_reset_rate_limit_backoff`).
    """
    global _rate_limit_until, _rate_limit_current_cooldown  # noqa: PLW0603
    with _rate_limit_lock:
        _rate_limit_until = datetime.fromtimestamp(_time_source(), tz=UTC) + timedelta(
            seconds=_rate_limit_current_cooldown
        )
        logger.warning(
            "GitHub API rate limit hit — pausing ALL gh/git calls for %ds",
            _rate_limit_current_cooldown,
        )
        _rate_limit_current_cooldown = min(
            _rate_limit_current_cooldown * 2, _RATE_LIMIT_MAX_COOLDOWN_SECONDS
        )


def _reset_rate_limit_backoff() -> None:
    """Reset the exponential backoff to the base cooldown after a successful call."""
    global _rate_limit_current_cooldown  # noqa: PLW0603
    with _rate_limit_lock:
        _rate_limit_current_cooldown = _RATE_LIMIT_COOLDOWN_SECONDS


async def _wait_for_rate_limit_cooldown() -> None:
    """If a global rate-limit cooldown is active, sleep until it expires.

    Polls ``_rate_limit_until`` every ``_RATE_LIMIT_POLL_INTERVAL`` seconds so
    callers pick up deadlines extended by concurrent ``_trigger_rate_limit_cooldown``
    calls while sleeping.
    """
    while True:
        deadline = _rate_limit_until
        if deadline is None:
            return
        remaining = (
            deadline - datetime.fromtimestamp(_time_source(), tz=UTC)
        ).total_seconds()
        if remaining <= 0:
            return
        logger.info(
            "Rate-limit cooldown active — waiting %.0fs before gh/git call",
            remaining,
        )
        await asyncio.sleep(min(remaining, _RATE_LIMIT_POLL_INTERVAL))


class AuthenticationError(RuntimeError):
    """Raised when a subprocess fails due to GitHub authentication issues."""


class SubprocessTimeoutError(RuntimeError):
    """Raised when a subprocess exceeds its allowed execution time."""


class CircuitBreakerOpenError(RuntimeError):
    """Raised when the gh/git circuit breaker is OPEN and short-circuits a call.

    Distinct from a transient failure: recent gh/git calls failed repeatedly
    (likely GitHub or the network is down), so we fail fast instead of piling
    on. The message contains none of ``_RETRYABLE_PATTERNS`` so
    ``run_subprocess_with_retry`` will not retry it.
    """


class CreditExhaustedError(RuntimeError):
    """Raised when a subprocess fails because API credits are exhausted.

    Attributes
    ----------
    resume_at:
        The datetime (UTC) when credits are expected to reset, or ``None``
        if no reset time could be parsed from the error output.
    """

    def __init__(self, message: str = "", *, resume_at: datetime | None = None) -> None:
        super().__init__(message)
        self.resume_at = resume_at


_AUTH_PATTERNS = ("401", "not logged in", "authentication required", "auth token")

_CREDIT_PATTERNS = (
    "usage limit reached",
    "credit balance is too low",
    "you've hit your limit",
    "hit your usage limit",
    # Claude Code subscription *session*-cap message
    # ("You've hit your session limit · resets 5:50am"). The word "session"
    # sits between "hit your" and "limit", so none of the usage-limit
    # substrings above match it — both renderings are pinned here.
    # (2026-06-13 incident; see tests/regressions/test_session_limit_credit_pause.py.)
    "hit your session limit",
    "session limit reached",
    # Anthropic API spend-cap rejection (HTTP 400 invalid_request_error).
    # Full phrase — narrower patterns would false-match conversational
    # transcript text like "reached your specified goals" and trigger a
    # non-retryable halt on every run.
    "reached your specified api usage limits",
    "reached your specified usage limits",
)

# Matches e.g. "reset at 3pm (America/New_York)", "reset at 3am",
# "resets 5am (America/Denver)", "resets at 5am", "resets 5:50am (America/Denver)".
# The minutes group is optional so both whole-hour and H:MM renderings parse —
# Claude Code's session-limit line carries minutes ("resets 5:50am").
_RESET_TIME_RE = re.compile(
    r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)"
    r"(?:\s*\(([^)]+)\))?",
    re.IGNORECASE,
)

# Matches Anthropic's ISO-style spend-cap resume format:
# "regain access on 2026-05-01 at 00:00 UTC"
# UTC is REQUIRED — if Anthropic ever changes the timezone (or omits it),
# we'd rather fail-to-parse than silently misinterpret the resume time.
_ISO_RESUME_TIME_RE = re.compile(
    r"regain\s+access\s+on\s+"
    r"(\d{4})-(\d{2})-(\d{2})"
    r"\s+at\s+(\d{1,2}):(\d{2})"
    r"\s+UTC\b",
    re.IGNORECASE,
)


_DOCKER_ENV_PASSTHROUGH_KEYS = (
    # Primary provider auth keys
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    # Gemini auth-method selection / Vertex project for non-API-key flows
    "GOOGLE_GENAI_USE_VERTEXAI",
    "GOOGLE_GENAI_USE_GCA",
    "GOOGLE_CLOUD_PROJECT",
    "XAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "MISTRAL_API_KEY",
    "TOGETHER_API_KEY",
    "GROQ_API_KEY",
    "PERPLEXITY_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_API_KEY",
    # Local agent config locations
    "PI_CODING_AGENT_DIR",
    "CODEX_HOME",
    "CLAUDE_CONFIG_DIR",
)


def is_credit_exhaustion(text: str) -> bool:
    """Check if *text* indicates an API credit exhaustion condition."""
    text_lower = text.lower()
    return any(p in text_lower for p in _CREDIT_PATTERNS)


async def probe_credit_availability() -> bool:
    """Make a lightweight Anthropic API call to check if credits are available.

    Returns ``True`` if credits appear available (or if the check cannot be
    performed), ``False`` if the API responds with a credit-exhaustion error.
    """
    import os

    import httpx

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        # No API key configured — cannot probe, assume available.
        return True

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
            if resp.status_code == 200:
                return True
            # Check response body for credit exhaustion patterns
            return not is_credit_exhaustion(resp.text)
    except (httpx.HTTPError, OSError):
        # Transient network error (DNS, connect, timeout, unreachable) — assume
        # credits ARE available so agents don't stall on flaky DNS/proxy (#6381).
        # Bugs (KeyError/TypeError from a malformed response) are NOT caught
        # here — they propagate so they surface in logs instead of silently
        # returning False.
        return True


def parse_credit_resume_time(text: str) -> datetime | None:
    """Extract the credit reset time from an error message.

    Looks for patterns like ``"reset at 3pm (America/New_York)"``,
    ``"reset at 3am"``, or ``"resets 5am (America/Denver)"``.
    Returns a timezone-aware UTC datetime, or ``None`` if no
    parseable time is found.

    When the parsed time is already past, we assume the reset is
    tomorrow at the same time.

    Also recognizes Anthropic's spend-cap format
    ``"regain access on 2026-05-01 at 00:00 UTC"`` and returns the exact
    UTC datetime without the past-time roll-forward (the date is explicit).
    """
    iso_match = _ISO_RESUME_TIME_RE.search(text)
    if iso_match:
        year, month, day, hour, minute = (
            int(iso_match.group(1)),
            int(iso_match.group(2)),
            int(iso_match.group(3)),
            int(iso_match.group(4)),
            int(iso_match.group(5)),
        )
        try:
            return datetime(year, month, day, hour, minute, tzinfo=UTC)
        except ValueError:
            return None

    match = _RESET_TIME_RE.search(text)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2)) if match.group(2) else 0
    ampm = match.group(3).lower()
    tz_name = match.group(4)

    # Validate 12-hour clock range (1–12) and minutes (0–59). A bogus minute
    # ("5:99am") fails to parse rather than rolling over into the next hour.
    if hour < 1 or hour > 12 or minute > 59:
        return None

    # Convert 12-hour to 24-hour
    if ampm == "am":
        hour_24 = 0 if hour == 12 else hour
    else:
        hour_24 = hour if hour == 12 else hour + 12

    # Resolve timezone
    tz = UTC
    if tz_name:
        try:
            tz = ZoneInfo(tz_name.strip())
        except (KeyError, ValueError):
            logger.warning(
                "Could not parse timezone %r — falling back to local time", tz_name
            )
            tz = datetime.now().astimezone().tzinfo or UTC

    now = datetime.now(tz=tz)
    reset = now.replace(hour=hour_24, minute=minute, second=0, microsecond=0)

    # If the reset time is already past, assume it means tomorrow
    if reset <= now:
        reset += timedelta(days=1)

    return reset.astimezone(UTC)


def _is_auth_error(stderr: str) -> bool:
    """Check if stderr indicates a GitHub authentication failure."""
    stderr_lower = stderr.lower()
    return any(p in stderr_lower for p in _AUTH_PATTERNS)


def make_clean_env(gh_token: str = "") -> dict[str, str]:
    """Build a subprocess env dict with ``CLAUDECODE`` stripped.

    Also strips ``GIT_WORK_TREE`` and ``GIT_DIR`` to prevent git
    worktree corruption — these env vars override git's internal
    resolution and cause ``core.worktree`` to be written to the
    config, corrupting the repo for subsequent operations.

    When *gh_token* is non-empty it is injected as ``GH_TOKEN``.
    """
    env = {**os.environ}
    env.pop("CLAUDECODE", None)
    env.pop("GIT_WORK_TREE", None)
    env.pop("GIT_DIR", None)
    if gh_token:
        env["GH_TOKEN"] = gh_token
    return env


def _read_dotenv(repo_root: Path) -> dict[str, str]:
    """Read key=value pairs from ``repo_root/.env`` for Docker passthrough."""
    env_file = repo_root / ".env"
    if not env_file.is_file():
        return {}
    try:
        text = env_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()  # noqa: PLW2901
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()  # noqa: PLW2901
        val = val.strip().strip("\"'")
        if key and val:
            result[key] = val
    return result


def make_docker_env(
    gh_token: str = "",
    git_user_name: str = "",
    git_user_email: str = "",
    repo_root: Path | None = None,
) -> dict[str, str]:
    """Build a minimal env dict for Docker container execution.

    Unlike :func:`make_clean_env` which inherits the full host env, this
    passes only the variables necessary for agent operation inside a container.

    When *repo_root* is provided, keys not found in ``os.environ`` are
    looked up in ``repo_root/.env`` so that values like
    ``CLAUDE_CODE_OAUTH_TOKEN`` reach the container even when they are
    only set in the dotenv file.
    """
    env: dict[str, str] = {"HOME": "/home/hydraflow"}
    dotenv = _read_dotenv(repo_root) if repo_root else {}

    if gh_token:
        env["GH_TOKEN"] = gh_token
    else:
        inherited_token = os.environ.get("GH_TOKEN", "") or os.environ.get(
            "GITHUB_TOKEN", ""
        )
        if inherited_token:
            env["GH_TOKEN"] = inherited_token

    for key in _DOCKER_ENV_PASSTHROUGH_KEYS:
        value = os.environ.get(key, "") or dotenv.get(key, "")
        if value:
            env[key] = value

    if git_user_name:
        env["GIT_AUTHOR_NAME"] = git_user_name
        env["GIT_COMMITTER_NAME"] = git_user_name
    if git_user_email:
        env["GIT_AUTHOR_EMAIL"] = git_user_email
        env["GIT_COMMITTER_EMAIL"] = git_user_email

    return env


_GH_COMMANDS = frozenset({"gh", "git"})


async def run_subprocess(
    *cmd: str,
    cwd: Path | None = None,
    gh_token: str = "",
    timeout: float = 120.0,
    runner: SubprocessRunner | None = None,
) -> str:
    """Run a subprocess and return stripped stdout.

    Strips the ``CLAUDECODE`` key from the environment to prevent
    nesting detection.  When *gh_token* is non-empty it is injected
    as ``GH_TOKEN``.

    For ``gh`` and ``git`` commands, execution is gated through a global
    semaphore to prevent GitHub API rate limiting from concurrent calls.

    Raises :class:`SubprocessTimeoutError` if the command exceeds *timeout* seconds.
    Raises :class:`RuntimeError` on non-zero exit.
    """
    from execution import get_default_runner

    env = make_clean_env(gh_token)

    resolved_runner = runner if runner is not None else get_default_runner()

    use_semaphore = bool(cmd) and cmd[0] in _GH_COMMANDS
    # The circuit breaker guards the GitHub API (``gh``) specifically — NOT local
    # ``git``. A repeated ``git`` failure (merge conflict, "nothing to commit", a
    # corrupted worktree) is not a GitHub-down signal, and counting it could trip
    # this PROCESS-GLOBAL breaker and halt all gh/git factory-wide on a purely
    # local problem. ``gh`` failures are the clean outage signal. Enabled state
    # (the live kill-switch) is re-read here each call, so a runtime toggle takes
    # effect on the next subprocess.
    breaker = (
        _gh_circuit_breaker
        if bool(cmd) and cmd[0] == "gh" and _gh_circuit_breaker_enabled
        else None
    )

    async def _exec() -> str:
        try:
            result = await resolved_runner.run_simple(
                list(cmd),
                cwd=str(cwd) if cwd is not None else None,
                env=env,
                timeout=timeout,
            )
        except TimeoutError as exc:
            if breaker is not None:
                breaker.record_failure()
            raise SubprocessTimeoutError(
                f"Command {cmd!r} timed out after {timeout}s"
            ) from exc
        if result.returncode != 0:
            # Sample the failure shape too — a loop that branches on a
            # specific stderr (404, "not found", auth errors) needs that
            # shape protected against drift just as much as success.
            _maybe_sample_shadow(cmd, result.returncode, result.stdout, result.stderr)
            msg = f"Command {cmd!r} failed (rc={result.returncode}): {result.stderr}"
            cause = subprocess.CalledProcessError(
                result.returncode,
                list(cmd),
                output=result.stdout,
                stderr=result.stderr,
            )
            if _is_auth_error(result.stderr):
                # Auth failure = bad/again-rejected credentials, not an outage;
                # opening the breaker wouldn't help (the token is still bad after
                # the reset window), so it must not count toward it.
                raise AuthenticationError(msg) from cause
            if _is_rate_limited(result.stderr):
                _trigger_rate_limit_cooldown()
                # A rate limit has its own global cooldown and is not a
                # GitHub-down signal, so it must NOT count toward the breaker.
                raise RuntimeError(msg) from cause
            # Count toward the breaker ONLY genuine GitHub/network outages — a
            # 4xx / business-logic non-zero exit (404, "label does not exist",
            # "cannot approve your own pull request", …) is normal control flow
            # and must not accumulate toward an OPEN that halts the factory.
            if breaker is not None and _is_gh_outage_error(result.stderr):
                breaker.record_failure()
            raise RuntimeError(msg) from cause
        _reset_rate_limit_backoff()
        if breaker is not None:
            breaker.record_success()
        _maybe_sample_shadow(cmd, result.returncode, result.stdout, result.stderr)
        return result.stdout

    if use_semaphore:
        if breaker is not None and not breaker.allow_request():
            # Fail fast: recent gh/git calls failed repeatedly (likely GitHub or
            # the network is down). The message intentionally avoids retryable
            # keywords so run_subprocess_with_retry won't retry it.
            raise CircuitBreakerOpenError(
                f"gh/git circuit breaker OPEN ({breaker.max_failures}+ "
                "consecutive failures); failing fast instead of hammering a "
                "likely-down GitHub. Recovers after the reset window."
            )
        await _wait_for_rate_limit_cooldown()
        async with _get_gh_semaphore():
            return await _exec()
    return await _exec()


_RETRYABLE_PATTERNS = (
    "timeout",
    "timed out",
    "connection",
    "502",
    "503",
    "504",
)
# Rate-limit errors are handled by the global cooldown in run_subprocess(),
# not by per-call retries which would just amplify the problem.
# "exceeds the maximum limit" is GitHub's GraphQL node-cost error — a
# deterministic too-expensive-query failure that will never succeed on retry,
# yet its message contains the substring "connection" (e.g. "authors
# connection"), so without this guard _RETRYABLE_PATTERNS would retry it 3×.
_NON_RETRYABLE_PATTERNS = ("401", "403", "404", "exceeds the maximum limit")


def _is_retryable_error(stderr: str) -> bool:
    """Check if a subprocess error indicates a transient/retryable condition.

    Rate-limit errors (403 + "rate limit") are NOT retried per-call;
    they trigger a global cooldown in :func:`run_subprocess` instead.
    """
    stderr_lower = stderr.lower()
    for pattern in _NON_RETRYABLE_PATTERNS:
        if pattern in stderr_lower:
            return False
    return any(p in stderr_lower for p in _RETRYABLE_PATTERNS)


async def run_subprocess_with_retry(
    *cmd: str,
    cwd: Path | None = None,
    gh_token: str = "",
    max_retries: int = 3,
    base_delay_seconds: float = 1.0,
    max_delay_seconds: float = 30.0,
    timeout: float = 120.0,
    runner: SubprocessRunner | None = None,
) -> str:
    """Run a subprocess with exponential backoff retry on transient errors.

    Retries on: rate-limit, timeout, connection errors, 502/503/504.
    Does NOT retry on: auth (401), forbidden (403 without rate-limit), not-found (404).

    Raises :class:`RuntimeError` after all retries are exhausted.
    """
    last_error: RuntimeError | None = None
    for attempt in range(max_retries + 1):
        try:
            return await run_subprocess(
                *cmd, cwd=cwd, gh_token=gh_token, timeout=timeout, runner=runner
            )
        except RuntimeError as exc:
            if isinstance(
                exc,
                AuthenticationError | CreditExhaustedError | CircuitBreakerOpenError,
            ):
                raise
            last_error = exc
            error_msg = str(exc)
            if attempt >= max_retries or not _is_retryable_error(error_msg):
                raise
            delay = min(base_delay_seconds * (2**attempt), max_delay_seconds)
            jitter = random.uniform(0, delay * 0.5)  # noqa: S311
            total_delay = delay + jitter
            logger.warning(
                "Retryable error (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1,
                max_retries,
                total_delay,
                error_msg[:200],
            )
            await asyncio.sleep(total_delay)
    # Should not reach here, but satisfy type checker
    assert last_error is not None  # noqa: S101
    raise last_error
