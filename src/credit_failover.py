"""Runtime credit-failover state and spawn routing (#10844).

Single owner of whether work spawns are currently rerouted from Claude to the
z.ai GLM backend because Claude subscription credits were exhausted. In-memory
module singleton: the orchestrator :func:`engage`\\ s it on an authoritative
Anthropic credit cap; the switch-back probe loop :func:`clear`\\ s it when Claude
recovers. Read at spawn time by ``base_runner`` via :func:`apply_credit_failover`.

State is deliberately in-memory (v1): on a restart mid-failover the first Claude
work spawn simply re-caps and re-engages — one bounded wasted spawn, not a
correctness bug. Persistence across restarts is a follow-up.

Module-global mutable state: :func:`reset_for_tests` is the reset hook (see the
autouse fixture in ``tests/conftest.py``), matching the #10889 module-state
reset-coverage pattern.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from prompt_telemetry import rewrite_command_model

if TYPE_CHECKING:
    from config import HydraFlowConfig

# The env keys the zai harness backend reads (mirrors runner_utils `_HARNESS_BACKENDS`
# `api_key_envs` for zai). Failover is a no-op without one of these set, because
# `resolve_harness_env` would otherwise silently fall back to the Claude endpoint.
# Any zai credential enables failover: the harness lane prefers the coding-
# plan key (flat-rate) and falls back to the API key — see
# runner_utils._HARNESS_BACKENDS.
_ZAI_API_KEY_ENVS = (
    "ZAI_CODING_PLAN_KEY",
    "HYDRAFLOW_ZAI_CODING_PLAN_KEY",
    "ZAI_API_KEY",
    "HYDRAFLOW_ZAI_API_KEY",
)


@dataclass(frozen=True)
class FailoverStatus:
    """Immutable snapshot of failover state (for logging / dashboard)."""

    engaged_at: datetime | None
    probe_after: datetime | None

    @property
    def active(self) -> bool:
        return self.engaged_at is not None


@dataclass
class _MutableState:
    """The single mutable holder. Attributes are mutated in place (never the name
    rebound) so no ``global`` statement — and no ``PLW0603`` — is needed."""

    engaged_at: datetime | None = None
    probe_after: datetime | None = None


_state = _MutableState()


def is_active() -> bool:
    """True while work spawns are rerouted to GLM (until an explicit clear)."""
    return _state.engaged_at is not None


def status() -> FailoverStatus:
    """An immutable snapshot of the current failover state."""
    return FailoverStatus(engaged_at=_state.engaged_at, probe_after=_state.probe_after)


def _probe_after_for(
    now: datetime, resume_at: datetime | None, cooldown_minutes: int
) -> datetime:
    # Use the error's reset time when it is still in the future, else a cooldown.
    if resume_at is not None and resume_at > now:
        return resume_at
    return now + timedelta(minutes=cooldown_minutes)


def engage(*, now: datetime, resume_at: datetime | None, cooldown_minutes: int) -> None:
    """Enter failover: route work spawns to GLM; schedule the first Claude probe."""
    _state.engaged_at = now
    _state.probe_after = _probe_after_for(now, resume_at, cooldown_minutes)


def advance_probe(*, now: datetime, cooldown_minutes: int) -> None:
    """A probe found Claude still capped — push the next probe out by a cooldown."""
    if _state.engaged_at is None:
        return
    _state.probe_after = now + timedelta(minutes=cooldown_minutes)


def probe_due(now: datetime) -> bool:
    """True when failover is active and it is time to probe Claude for switch-back."""
    return (
        _state.engaged_at is not None
        and _state.probe_after is not None
        and now >= _state.probe_after
    )


def rearm_probe(*, now: datetime) -> bool:
    """Re-arm a stuck switch-back probe so the next tick is eligible immediately.

    A safe, reversible in-memory nudge (ADR-0124): when failover is active it
    sets ``probe_after`` to *now* so the orchestrator's probe becomes due on its
    next pass; the probe itself still decides switch-back vs another cooldown.
    Returns ``True`` when it re-armed an active failover, ``False`` otherwise.
    """
    if _state.engaged_at is None:
        return False
    _state.probe_after = now
    return True


def clear() -> None:
    """Exit failover: work spawns route back to Claude."""
    _state.engaged_at = None
    _state.probe_after = None


def reset_for_tests() -> None:
    """Reset module state between tests (autouse fixture)."""
    clear()


def zai_key_present() -> bool:
    """Whether a z.ai API key is available for the harness backend."""
    return any(os.environ.get(k, "").strip() for k in _ZAI_API_KEY_ENVS)


def apply_credit_failover(
    provider: str, cmd: list[str], config: HydraFlowConfig
) -> tuple[str, list[str]]:
    """Reroute a Claude work spawn to zai/GLM while failover is active.

    Returns ``(provider, cmd)`` unchanged unless ALL hold: the spawn is on
    ``claude``, ``credit_failover_enabled``, failover is currently active, and a
    ``ZAI_API_KEY`` is present. When rerouting, the ``--model`` in *cmd* is
    rewritten to ``config.credit_failover_model`` (the zai backend requires a
    glm-* model). The input *cmd* is never mutated.
    """
    if provider not in {"claude", "gateway"}:
        return provider, cmd
    if not config.credit_failover_enabled:
        return provider, cmd
    if not is_active():
        return provider, cmd
    # A gateway-routed failover keeps the transport and mints a z.ai-bound
    # virtual key from the rewritten GLM model; the worker must not require or
    # receive a real local z.ai credential. Direct Claude retains the existing
    # key-presence guard byte-for-byte.
    if provider == "claude" and not zai_key_present():
        return provider, cmd
    resolved_provider = "gateway" if provider == "gateway" else "zai"
    return resolved_provider, rewrite_command_model(cmd, config.credit_failover_model)
