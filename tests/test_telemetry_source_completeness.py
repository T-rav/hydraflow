"""Factory validation: every LLM inference is visible to telemetry (WS-2.2).

PromptTelemetry is recorded ONLY by the central runners (``BaseRunner._execute``,
``BaseSubprocessRunner.run``) and the ``runner_utils`` wrappers
(``stream_claude_with_telemetry``, ``run_lightweight_agent``). A module that
calls a RAW spawn primitive (``stream_claude_process`` or
``build_lightweight_command``) directly — or hand-builds an agent CLI argv and
calls ``run_simple`` — bypasses telemetry, so its spend is invisible to the cost
cap / ROI dashboard (the ``untelemetried-llm-spawners`` audit finding).

SCOPE OF THE GUARANTEE: this is a *containment* ratchet over known spawn
primitives + a hand-rolled-argv heuristic. It fails closed when a new spawner
routes around the wrappers via those signals; it cannot prove a module records
telemetry, only that it does not bypass the recording seam. ``_GRANDFATHERED``
must shrink toward empty and must never grow.

Ref: ADR-0055 (telemetry/credit contract for spawn paths),
``docs/wiki/dark-factory.md`` §6.
"""

from __future__ import annotations

from tests._spawn_audit import iter_module_facts

# Raw LLM-spawn primitives. Calling either directly bypasses the telemetry
# recording that the wrappers/central runners perform.
_RAW_PRIMITIVES = frozenset({"stream_claude_process", "build_lightweight_command"})

# Modules permitted to call the raw primitives, keyed by path RELATIVE to src/
# (not bare filename — a future src/<subdir>/runner_utils.py must NOT inherit
# this exemption). These are the wrappers' home + the two central runners that
# record PromptTelemetry around their own spawn.
_APPROVED = frozenset(
    {
        "runner_utils.py",  # defines stream_claude_process + the recording wrappers
        "base_runner.py",  # BaseRunner._execute records telemetry in a finally
        "runners/base_subprocess_runner.py",  # BaseSubprocessRunner.run records telemetry
    }
)

# Ratchet allow-list (rel paths). Each entry is a known-untelemetried lightweight
# spawner whose telemetry backfill is blocked on threading a HydraFlowConfig into
# a constructor that has none today (touches service_registry + many test
# constructions). Credit IS handled for both. Tracked as the WS-2.2 telemetry
# follow-up. MUST shrink toward empty and MUST NOT grow.
_GRANDFATHERED = frozenset(
    {
        "term_proposer_runtime.py",  # ClaudeCLIClient has no config field
        "adversarial_agent_runner.py",  # SubprocessAgentRunner @dataclass, no config
    }
)


def _untelemetried_spawners() -> set[str]:
    """Return non-approved modules that spawn an LLM without a recording seam."""
    offenders: set[str] = set()
    for facts in iter_module_facts():
        if facts.rel in _APPROVED:
            continue
        bypasses_primitive = bool(facts.calls & _RAW_PRIMITIVES)
        hand_rolled_argv = "run_simple" in facts.calls and facts.has_agent_argv
        if bypasses_primitive or hand_rolled_argv:
            offenders.add(facts.rel)
    return offenders


def test_no_llm_spawn_bypasses_telemetry() -> None:
    offenders = sorted(_untelemetried_spawners() - _GRANDFATHERED)
    assert not offenders, (
        "These modules spawn an LLM without routing through a telemetry-recording "
        f"seam (raw {sorted(_RAW_PRIMITIVES)}, or hand-built agent argv + run_simple), "
        f"so their spend is invisible to the cost cap: {offenders}. Route the spawn "
        "through runner_utils.stream_claude_with_telemetry or run_lightweight_agent "
        "(or subclass BaseRunner/BaseSubprocessRunner), which record PromptTelemetry."
    )


def test_telemetry_grandfather_only_real_spawners() -> None:
    """A stale grandfather entry (no longer an untelemetried spawner) must be removed."""
    offenders = _untelemetried_spawners()
    stale = sorted(_GRANDFATHERED - offenders)
    assert not stale, (
        f"_GRANDFATHERED has stale entries that no longer bypass telemetry: {stale}. "
        "Remove them — the ratchet is already satisfied for these files."
    )


def test_approved_recorders_actually_record_telemetry() -> None:
    """Keep the allow-list honest: each approved module must still record."""
    facts = {f.rel: f for f in iter_module_facts()}
    for rel in sorted(_APPROVED):
        assert rel in facts, f"approved recorder {rel} not found in src/"
        assert "record" in facts[rel].calls, (
            f"{rel} is an approved telemetry recorder but no longer calls .record(); "
            "it may have stopped recording — fix the recorder or update _APPROVED."
        )
