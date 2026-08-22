"""Credit-pause and GLM-failover subsystem of :class:`orchestrator.HydraFlowOrchestrator`.

Extracted VERBATIM from ``orchestrator.py`` (god-class decomposition, Refs
#11547) as a mixin; ``HydraFlowOrchestrator`` inherits
:class:`OrchestratorCreditsMixin`.

One cohesive concern: what the factory does when a billing provider says no.
The corroborating probe, the #10844 failover to GLM plus its switch-back
probe, the per-provider blast-radius computation (#9807) that decides which
loops a given exhaustion must pause, the pause itself, and the resume that
rebuilds the paused loop tasks.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Coroutine, Iterable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import credit_failover
from config import resolve_maintenance_model
from events import EventType, HydraFlowEvent
from models import SystemAlertPayload
from orchestrator_common import _BACKEND_WORKER_LOOPS, _PRIMARY_WORK_LOOP_TO_TOOL_FIELD
from runner_utils import (
    backend_probe_endpoint,
    harness_billing_provider,
    normalize_provider,
    reap_all_tracked_processes,
)
from subprocess_util import (
    PROVIDER_ANTHROPIC,
    CreditExhaustedError,
    probe_credit_availability,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from events import EventBus
    from service_registry import ServiceRegistry

# Same logger as the host — the moved code's records keep their
# pre-extraction ``hydraflow.orchestrator`` origin.
logger = logging.getLogger("hydraflow.orchestrator")


class OrchestratorCreditsMixin:
    """Credit-pause and GLM-failover subsystem of :class:`orchestrator.HydraFlowOrchestrator`."""

    # ------------------------------------------------------------------
    # Collaborator seams — attributes and methods provided by HydraFlowOrchestrator or a
    # sibling mixin. The method declarations are TYPE_CHECKING-only on
    # purpose: a runtime ``...`` body would take precedence over the real
    # implementation whenever the declaring mixin precedes the implementing
    # one in the host's MRO (#11629).
    # ------------------------------------------------------------------
    _bus: EventBus
    _config: HydraFlowConfig
    _credit_fp_last: dict[str, datetime]
    _credit_pause_lock: asyncio.Lock
    _credit_paused_provider: str | None
    _credit_resume_event: asyncio.Event
    _credits_paused_until: datetime | None
    _failover_probe_task: asyncio.Task[None] | None
    _stop_event: asyncio.Event
    _svc: ServiceRegistry

    if TYPE_CHECKING:

        async def _restart_loop(
            self,
            loop_name: str,
            exc: BaseException,
            tasks: dict[str, asyncio.Task[None]],
            loop_factories: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]],
            restart_delay: float = 0.0,
        ) -> None: ...  # provided by OrchestratorRestartMixin

        async def _sleep_or_stop(
            self, seconds: int | float
        ) -> None: ...  # provided by OrchestratorLoopsMixin

    @property
    def credits_paused_until(self) -> datetime | None:
        """The UTC datetime when credit pause ends, or ``None``."""
        if (
            self._credits_paused_until is not None
            and self._credits_paused_until > datetime.now(UTC)
        ):
            return self._credits_paused_until
        return None

    @property
    def credits_paused_provider(self) -> str | None:
        """The billing provider the ACTIVE credit pause is scoped to, or ``None``
        (no active pause, or a global/legacy pause). Surfaced in the status
        payload so the UI can show *which* backend is paused (#9807)."""
        if self.credits_paused_until is not None:
            return self._credit_paused_provider
        return None

    def clear_credit_pause(self) -> None:
        """Clear a credit pause early, waking ``_sleep_until_resume``."""
        self._credits_paused_until = None
        self._credit_paused_provider = None
        self._credit_resume_event.set()

    def try_clear_credit_pause(self) -> bool:
        """Attempt to clear the credit pause and resume loops early.

        Returns ``True`` if a pause was active and the resume signal was sent,
        ``False`` if no pause was active.
        """
        if self._credits_paused_until is None:
            return False
        self._credit_resume_event.set()
        return True

    async def _handle_credit_exhaustion(
        self,
        exc: CreditExhaustedError,
        loop_name: str,
        tasks: dict[str, asyncio.Task[None]],
        loop_factories: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]],
    ) -> None:
        """Pause on a corroborated credit signal; otherwise restart the loop.

        A probe-refuted (false-positive) signal must not leave the crashed
        loop's completed-with-exception task orphaned in ``_supervise_loops``'s
        task map: the supervisor would re-observe the same dead task every
        iteration and hot-loop the credit handler (alert storm), and the phase
        would stay permanently dead. Recreating the task via ``_restart_loop``
        — the same path used for any other loop crash — kills the hot loop and
        self-heals the phase. See #9924.

        Credit failover (#10844): an *authoritative* Claude cap short-circuits to
        engaging GLM failover and restarting the crashed loop NOW — it re-runs
        routed to GLM (base_runner reroutes while failover is active) instead of
        pausing the factory. Everything else (prose-only signals, non-Claude
        caps, no zai key, disabled) falls through to the unchanged pause logic.
        """
        if await self._maybe_engage_failover(exc, loop_name):
            await self._restart_loop(loop_name, exc, tasks, loop_factories)
            return
        paused = await self._pause_for_credits(exc, loop_name, tasks, loop_factories)
        if not paused:
            # Suppressed false positive: restart with a delay so a loop that
            # re-raises the same quoted-prose signal cannot tight-spin the
            # supervisor (#9888). The delay lives inside the restarted task,
            # never blocking supervision of other loops.
            await self._restart_loop(
                loop_name,
                exc,
                tasks,
                loop_factories,
                restart_delay=min(
                    float(self._config.credit_fp_suppress_cooldown_seconds), 60.0
                ),
            )

    async def _maybe_engage_failover(
        self, exc: CreditExhaustedError, loop_name: str | None = None
    ) -> bool:
        """Engage GLM failover for an authoritative Claude credit cap (#10844).

        Returns ``True`` when the caller should restart the crashed loop NOW (it
        re-runs routed to GLM) instead of pausing. Returns ``False`` — falling
        through to the unchanged pause/probe logic — for anything that is not a
        clear Claude cap we can fail over: the feature disabled, a non-Claude
        (zai/kimi) cap, a prose-only signal that still needs corroboration, or no
        a usable route to z.ai. Direct harness routes still require a local z.ai
        credential. A gateway-routed core work loop does not: the gateway owns
        the provider credential and the restarted worker receives only a new
        z.ai-bound virtual key. Idempotent while already failed over: it just
        re-signals "restart on GLM".
        """
        if not self._config.credit_failover_enabled:
            return False
        provider = getattr(exc, "provider", PROVIDER_ANTHROPIC) or PROVIDER_ANTHROPIC
        if provider not in (PROVIDER_ANTHROPIC, "claude"):
            return False
        if not getattr(exc, "authoritative", False):
            return False
        gateway_route = self._loop_uses_gateway_transport(loop_name)
        if not credit_failover.zai_key_present() and not gateway_route:
            return False
        if credit_failover.is_active():
            # Already failed over (possibly engaged by another repo's orchestrator
            # — the flag is process-global). Ensure THIS orchestrator has a live
            # switch-back probe too, so it isn't left to whichever instance first
            # observed the cap. Idempotent when a probe is already running.
            self._start_failover_probe()
            return True
        now = datetime.now(UTC)
        resume_at = self._compute_resume_time(exc)
        credit_failover.engage(
            now=now,
            resume_at=resume_at if resume_at > now else None,
            cooldown_minutes=int(self._config.credit_failover_cooldown_minutes),
        )
        logger.warning(
            "Claude credit cap (provider=%s) — engaging GLM failover; work "
            "reroutes to %s. First Claude switch-back probe at %s.",
            provider,
            self._config.credit_failover_model,
            credit_failover.status().probe_after,
        )
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SYSTEM_ALERT,
                data={
                    "message": (
                        "Claude credits exhausted — failing over to GLM "
                        f"({self._config.credit_failover_model}); work continues."
                    ),
                    "provider": provider,
                    "severity": "warning",
                },
            )
        )
        self._start_failover_probe()
        return True

    def _start_failover_probe(self) -> None:
        """Start the switch-back probe task if one is not already running."""
        if (
            self._failover_probe_task is not None
            and not self._failover_probe_task.done()
        ):
            return
        self._failover_probe_task = asyncio.create_task(
            self._run_failover_probe(), name="hydraflow-credit-failover-probe"
        )

    def _rearm_failover_probe_if_active(self) -> None:
        """Re-arm the switch-back probe on startup when failover is engaged (#10844).

        The failover flag is a process-global that survives an in-process
        stop/start (and is shared across orchestrators in multi-repo mode). If a
        prior run left it engaged, the probe must be re-armed here — otherwise a
        restart while failed over leaves work silently pinned to GLM: every spawn
        reroutes before it can raise a fresh ``CreditExhaustedError``, so
        ``_maybe_engage_failover`` (which arms the probe) is never reached again.
        Idempotent when a probe is already live.
        """
        if credit_failover.is_active():
            self._start_failover_probe()

    async def _run_failover_probe(self) -> None:
        """Poll for Claude recovery while failover is active; clear on success."""
        while credit_failover.is_active() and not self._stop_event.is_set():
            if await self._probe_claude_for_switchback():
                return
            # Poll no faster than a minute; ``_sleep_or_stop`` wakes on shutdown.
            await self._sleep_or_stop(60.0)

    async def _probe_claude_for_switchback(self) -> bool:
        """One switch-back attempt. Returns ``True`` when failover was cleared.

        Only probes once the scheduled ``probe_after`` has arrived (the error's
        reset time, or the cooldown). A successful probe clears failover so work
        routes back to Claude; the next real Claude spawn is the true arbiter (a
        probe cannot see a *weekly* cap), and if it re-caps, failover re-engages.
        A failed probe pushes the next attempt out by a cooldown.
        """
        now = datetime.now(UTC)
        if not credit_failover.probe_due(now):
            return False
        base_url, api_key = backend_probe_endpoint(PROVIDER_ANTHROPIC, self._config)
        available = await probe_credit_availability(
            PROVIDER_ANTHROPIC, base_url=base_url, api_key=api_key
        )
        if available:
            credit_failover.clear()
            logger.warning(
                "Claude credit probe succeeded — clearing GLM failover; work "
                "returns to Claude."
            )
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_ALERT,
                    data={
                        "message": "Claude credits recovered — switching back from GLM.",
                        "provider": PROVIDER_ANTHROPIC,
                        "severity": "info",
                    },
                )
            )
            return True
        credit_failover.advance_probe(
            now=now, cooldown_minutes=int(self._config.credit_failover_cooldown_minutes)
        )
        return False

    def _loop_uses_gateway_transport(self, loop_name: str | None) -> bool:
        """Whether a core work loop's next spawn resolves through the gateway.

        The explicit role dial wins. A still-Claude role may also inherit the
        repo-wide gateway override. The fleet ratchet is included as a final
        fail-safe for live config objects changed after validation. Non-core
        maintenance loops are excluded because their one-shot seam does not
        participate in work-spawn credit failover.
        """
        if loop_name not in _PRIMARY_WORK_LOOP_TO_TOOL_FIELD:
            return False
        route_fields = _BACKEND_WORKER_LOOPS[loop_name]
        provider = getattr(self._config, route_fields[0])
        if provider == "gateway":
            return True
        if provider != "claude":
            return False
        tool = getattr(self._config, _PRIMARY_WORK_LOOP_TO_TOOL_FIELD[loop_name])
        if tool != "claude":
            return False
        return bool(
            self._config.repo_provider == "gateway"
            or self._config.gateway_fleet_ratchet_enabled
        )

    def _loop_providers(self, loop_names: Iterable[str]) -> dict[str, str]:
        """Map each loop name to the billing provider its LLM work routes to.

        Loops in ``_BACKEND_WORKER_LOOPS`` read their configured provider/model
        pair.  The model is required because ``gateway`` is a transport: Claude
        models bill Anthropic while ``glm-*`` models bill z.ai.  Every other
        loop runs on the Claude harness → ``"anthropic"``. Read from live config
        so an operator's dial change takes effect on the next pause."""
        providers: dict[str, str] = {}
        for name in loop_names:
            route_fields = _BACKEND_WORKER_LOOPS.get(name)
            if route_fields is None:
                providers[name] = PROVIDER_ANTHROPIC
            else:
                dial_field, model_field = route_fields
                dial = getattr(self._config, dial_field)
                configured_model = getattr(self._config, model_field)
                model = (
                    resolve_maintenance_model(
                        role_model=configured_model,
                        maintenance_model=self._config.maintenance_model,
                        background_model=self._config.background_model,
                    )
                    if dial_field == "maintenance_provider"
                    else configured_model or "haiku"
                )
                providers[name] = normalize_provider(
                    harness_billing_provider(dial, model)
                )
        return providers

    def _affected_loops(
        self, provider: str, loop_names: Iterable[str], source: str
    ) -> tuple[set[str], bool]:
        """Which loops a *provider* exhaustion must pause, + whether to terminate
        the shared Claude-harness runner pools.

        - Unknown provider (``normalize_provider`` changes it) → GLOBAL fallback:
          pause every loop and terminate the runner pools (today's behavior).
        - ``"anthropic"`` → pause every anthropic-routed loop (all but the
          surviving backend workers) and terminate the harness pools.
        - A backend (``"zai"``/``"kimi"``/``"openrouter"``) → pause only loops
          routed there (always including *source*, which demonstrably routes to
          it since it raised the signal) and leave the harness pools running."""
        names = list(loop_names)
        provider_map = self._loop_providers(names)
        if normalize_provider(provider) != provider:
            # Provider the registry doesn't recognize — fail safe to a global pause.
            return set(names), True
        affected = {n for n, p in provider_map.items() if p == provider}
        if provider != PROVIDER_ANTHROPIC and source in provider_map:
            affected.add(source)
        return affected, provider == PROVIDER_ANTHROPIC

    def _compute_resume_time(self, exc: CreditExhaustedError) -> datetime:
        """Compute the UTC datetime at which credit pause should end."""
        buffer = timedelta(minutes=self._config.credit_pause_buffer_minutes)
        now = datetime.now(UTC)
        if exc.resume_at is not None:
            return exc.resume_at + buffer
        return now + timedelta(hours=5) + buffer

    async def _cancel_all_loops_and_runners(
        self,
        tasks: dict[str, asyncio.Task[None]],
        affected: set[str] | None = None,
        *,
        terminate_runners: bool = True,
    ) -> None:
        """Cancel the *affected* loop tasks and (optionally) terminate the
        Claude-harness subprocess pools.

        *affected* ``None`` means every loop (the global / Anthropic pause).
        A backend-scoped pause (z.ai/kimi/openrouter) passes only the loops
        routed to that backend and ``terminate_runners=False`` so the shared
        harness runner pools — which bill against Anthropic and belong to the
        surviving loops — are left untouched (#9807)."""
        to_cancel = (
            tasks if affected is None else {n: tasks[n] for n in affected if n in tasks}
        )
        for task in to_cancel.values():
            task.cancel()
        await asyncio.gather(*to_cancel.values(), return_exceptions=True)
        if terminate_runners:
            self._svc.planners.terminate()
            self._svc.agents.terminate()
            self._svc.reviewers.terminate()
            self._svc.hitl_runner.terminate()
            reap_all_tracked_processes()

    async def _sleep_until_resume(self, resume_at: datetime) -> None:
        """Sleep until *resume_at* (interruptible by stop or credit-resume event)."""
        pause_seconds = max((resume_at - datetime.now(UTC)).total_seconds(), 0)
        sleep_task = asyncio.create_task(self._sleep_or_stop(pause_seconds))
        resume_task = asyncio.create_task(self._credit_resume_event.wait())
        try:
            await asyncio.wait(
                {sleep_task, resume_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in (sleep_task, resume_task):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            self._credit_resume_event.clear()

    async def _pause_for_credits(
        self,
        exc: CreditExhaustedError,
        source: str,
        tasks: dict[str, asyncio.Task[None]],
        loop_factories: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]],
    ) -> bool:
        """Pause all loops until API credits reset, then restart them.

        Uses ``asyncio.Lock`` to prevent multiple loops from racing into
        the pause logic simultaneously.

        Returns ``True`` when a pause is committed (or one is already active) —
        the crashed task will be recreated by the resume path — and ``False``
        when the probe refutes the signal as a false positive and no pause
        happens, so the caller must restart the crashed loop itself (#9924).
        """
        async with self._credit_pause_lock:
            # If another loop already triggered a pause, skip
            if (
                self._credits_paused_until is not None
                and self._credits_paused_until > datetime.now(UTC)
            ):
                return True

            # Which backend hit the limit (#9807). Default "anthropic" — the
            # Claude harness — so every legacy raise site stays global-scoped;
            # the one-shot backends (z.ai/kimi/openrouter) tag their own signal.
            provider = (
                getattr(exc, "provider", PROVIDER_ANTHROPIC) or PROVIDER_ANTHROPIC
            )

            # Origin gate (#10558): an AUTHORITATIVE signal came from the
            # subprocess's own termination — the CLI's stderr / a structured HTTP
            # 402/429/quota body — and is ground truth. Only a signal scanned from
            # agent stdout PROSE (a diagnostic/reviewer run quoting a prior cap —
            # the #9895 CREDIT_PROSE_SCAN class) needs the probe. The auth/
            # availability probe structurally CANNOT detect a *weekly*-limit
            # exhaustion (the key stays valid, so the probe passes), so routing a
            # genuine weekly signal through it discarded it as a false positive and
            # the factory never paused — loops then crash-thrashed against the
            # exhausted budget. Corroborate prose-only signals; pause directly on
            # authoritative ones. Defaults to the conservative "corroborate"
            # stance so an untagged/unknown signal keeps the legacy probe gate.
            authoritative = getattr(exc, "authoritative", False)

            # Corroborate the text-detected signal with a live API probe before
            # committing a GLOBAL pause. ``is_credit_exhaustion`` matches
            # credit-error PROSE, so a diagnostic/reviewer run that merely quotes
            # a prior cap in its analysis would otherwise trigger a multi-hour
            # false global pause (#9807). The probe is ground truth: it returns
            # False only when the API itself confirms exhaustion, and fails open
            # (True on no-key/network error) so a flaky probe delays a real pause
            # by at most one detection cycle rather than masking it. Kill-switch:
            # ``credit_pause_require_probe=False`` reverts to pause-on-text.
            # ``and`` short-circuits: with the kill-switch off, the probe is
            # never called (pause-on-text, the legacy behavior).
            # Throttle repeat false positives from the same source (#9888):
            # within the cooldown, skip the probe AND the banner — log-only.
            # Six suppression banners landed in 3ms before this guard.
            fp_last = self._credit_fp_last.get(source)
            cooldown = float(self._config.credit_fp_suppress_cooldown_seconds)
            if (
                not authoritative
                and self._config.credit_pause_require_probe
                and fp_last is not None
                and (datetime.now(UTC) - fp_last).total_seconds() < cooldown
            ):
                logger.debug(
                    "Credit FP from %r within %.0fs cooldown — suppressed (log-only)",
                    source,
                    cooldown,
                )
                return False

            # Probe the AFFECTED backend, not always Anthropic (#9807): a z.ai
            # 429 is corroborated against z.ai's endpoint, a Claude cap against
            # Anthropic. Endpoint (base_url/api_key) resolves from the provider
            # registry; anthropic → ("","") which the probe ignores.
            probe_base_url, probe_api_key = backend_probe_endpoint(
                provider, self._config
            )
            if (
                not authoritative
                and self._config.credit_pause_require_probe
                and await probe_credit_availability(
                    provider, base_url=probe_base_url, api_key=probe_api_key
                )
            ):
                self._credit_fp_last[source] = datetime.now(UTC)
                logger.warning(
                    "Credit-exhaustion signal from %r (provider=%s) NOT "
                    "corroborated by live API probe — treating as a false "
                    "positive (likely quoted credit-error prose); not pausing.",
                    source,
                    provider,
                )
                await self._bus.publish(
                    HydraFlowEvent(
                        type=EventType.SYSTEM_ALERT,
                        data={
                            "message": (
                                "Credit signal not corroborated by API probe "
                                "— ignoring as a false positive."
                            ),
                            "source": source,
                            "provider": provider,
                            # Benign: a false positive was suppressed, nothing
                            # paused. Render yellow, not the red critical banner.
                            "severity": "warning",
                        },
                    )
                )
                return False

            resume_at = self._compute_resume_time(exc)
            self._credits_paused_until = resume_at
            self._credit_paused_provider = provider
            pause_seconds = max((resume_at - datetime.now(UTC)).total_seconds(), 0)

            # Scope the pause to the loops routed to this backend. Anthropic (or
            # an unrecognized provider) still pauses the whole factory except the
            # surviving backend workers; a z.ai/kimi cap pauses only its own
            # loops and leaves Claude work running (#9807).
            affected, terminate_runners = self._affected_loops(
                provider, tasks.keys(), source
            )
            scope = "all loops" if terminate_runners else f"{provider} loops"

            logger.warning(
                "Credit limit reached (detected in %r, provider=%s). "
                "Pausing %s until %s (%.0f minutes).",
                source,
                provider,
                scope,
                resume_at.isoformat(),
                pause_seconds / 60,
            )

            data: SystemAlertPayload = {
                "message": f"Credit limit reached ({provider}). Pausing {scope}.",
                "source": source,
                "provider": provider,
                "resume_at": resume_at.isoformat(),
            }
            await self._bus.publish(
                HydraFlowEvent(
                    type=EventType.SYSTEM_ALERT,
                    data=data,
                )
            )

            await self._cancel_all_loops_and_runners(
                tasks, affected, terminate_runners=terminate_runners
            )

        await self._sleep_until_resume(resume_at)

        if self._stop_event.is_set():
            self._credits_paused_until = None
            self._credit_paused_provider = None
            self._credit_resume_event.clear()
            return True

        await self._resume_loops_after_credit_pause(
            tasks, loop_factories, source, affected
        )
        return True

    async def _resume_loops_after_credit_pause(
        self,
        tasks: dict[str, asyncio.Task[None]],
        loop_factories: list[tuple[str, Callable[[], Coroutine[Any, Any, None]]]],
        source: str,
        affected: set[str] | None = None,
    ) -> None:
        """Clear pause state and restart the loops paused for this credit pause.

        *affected* ``None`` restarts every loop (global/legacy). A scoped pause
        passes the same set it cancelled so only those loops are recreated —
        the surviving backend/harness loops were never touched (#9807)."""
        if self._stop_event.is_set():
            # Stop landed during the pause: clear the pause state but do NOT
            # recreate any loop. ``_pause_for_credits`` already short-circuits
            # to this outcome before calling us; this guard also fail-safes any
            # future caller so a credit pause that ends after stop never leaks a
            # live loop past the shutdown drain and wedges "stopping" (#10569).
            self._credits_paused_until = None
            self._credit_paused_provider = None
            self._credit_resume_event.clear()
            return
        provider = self._credit_paused_provider
        self._credits_paused_until = None
        self._credit_paused_provider = None
        self._credit_resume_event.clear()
        scope = "all loops" if affected is None else f"{len(affected)} loop(s)"
        logger.info("Credit pause ended — restarting %s", scope)
        data: SystemAlertPayload = {
            "message": "Credit pause ended. Resuming loops.",
            "source": source,
        }
        if provider is not None:
            data["provider"] = provider
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SYSTEM_ALERT,
                data=data,
            )
        )
        for loop_name, factory in loop_factories:
            if affected is not None and loop_name not in affected:
                continue
            tasks[loop_name] = asyncio.create_task(
                factory(), name=f"hydraflow-{loop_name}"
            )
