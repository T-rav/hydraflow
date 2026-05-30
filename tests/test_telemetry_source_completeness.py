"""Factory validation: every LLM inference is visible to telemetry (WS-2.2).

PromptTelemetry is recorded ONLY by the central runners (``BaseRunner._execute``,
``BaseSubprocessRunner.run``) and the ``runner_utils`` wrappers
(``stream_claude_with_telemetry``, ``run_lightweight_agent``). A module that
calls a RAW spawn primitive (``stream_claude_process`` or
``build_lightweight_command``) directly bypasses telemetry, so its spend is
invisible to the cost cap / ROI dashboard — the ``untelemetried-llm-spawners``
finding from the dark-factory audit.

This is a *containment* ratchet: no module outside the approved recording set
may call a raw primitive. It fails closed when a new spawner is added that
skips the wrappers. ``_GRANDFATHERED`` must shrink toward empty and must never
grow.

Ref: ADR-0086, ``docs/wiki/dark-factory.md`` §6.
"""

from __future__ import annotations

from tests._spawn_audit import iter_module_facts

# Raw LLM-spawn primitives. Calling either directly bypasses the telemetry
# recording that the wrappers/central runners perform.
_RAW_PRIMITIVES = frozenset({"stream_claude_process", "build_lightweight_command"})

# Modules permitted to call the raw primitives: the wrappers' home and the two
# central runners that record PromptTelemetry around their own spawn.
_APPROVED = frozenset(
    {
        "runner_utils.py",  # defines stream_claude_process + the recording wrappers
        "base_runner.py",  # BaseRunner._execute records telemetry in a finally
        "base_subprocess_runner.py",  # BaseSubprocessRunner.run records telemetry
    }
)

# Ratchet allow-list. Each entry is a known-untelemetried lightweight spawner
# whose telemetry backfill is blocked on threading a HydraFlowConfig into a
# constructor that has none today (doing so touches service_registry + many
# test constructions). Credit IS handled for both. Tracked as the WS-2.2
# telemetry follow-up. MUST shrink toward empty and MUST NOT grow — a NEW
# raw-primitive caller fails ``test_no_llm_spawn_bypasses_telemetry``.
_GRANDFATHERED = frozenset(
    {
        "term_proposer_runtime.py",  # ClaudeCLIClient has no config field
        "adversarial_agent_runner.py",  # SubprocessAgentRunner @dataclass, no config
    }
)


def _raw_spawn_callers() -> set[str]:
    """Return non-approved modules that call a raw LLM spawn primitive."""
    return {
        facts.name
        for facts in iter_module_facts()
        if facts.name not in _APPROVED and (facts.calls & _RAW_PRIMITIVES)
    }


def test_no_llm_spawn_bypasses_telemetry() -> None:
    offenders = sorted(_raw_spawn_callers() - _GRANDFATHERED)
    assert not offenders, (
        "These modules call a raw LLM spawn primitive "
        f"({sorted(_RAW_PRIMITIVES)}) directly, bypassing telemetry — their spend "
        f"is invisible to the cost cap: {offenders}. Route the spawn through "
        "runner_utils.stream_claude_with_telemetry or run_lightweight_agent (or "
        "subclass BaseRunner/BaseSubprocessRunner), which record PromptTelemetry."
    )


def test_telemetry_grandfather_only_real_spawners() -> None:
    """A stale grandfather entry (no longer a raw caller) must be removed."""
    callers = _raw_spawn_callers()
    stale = sorted(_GRANDFATHERED - callers)
    assert not stale, (
        f"_GRANDFATHERED has stale entries that no longer call a raw primitive: "
        f"{stale}. Remove them — the ratchet is already satisfied for these files."
    )


def test_approved_recorders_actually_record_telemetry() -> None:
    """Keep the allow-list honest: each approved module must still record."""
    facts = {f.name: f for f in iter_module_facts()}
    for name in sorted(_APPROVED):
        assert name in facts, f"approved recorder {name} not found in src/"
        assert "record" in facts[name].calls, (
            f"{name} is an approved telemetry recorder but no longer calls .record(); "
            "it may have stopped recording — fix the recorder or update _APPROVED."
        )
