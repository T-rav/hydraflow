"""Factory validation: every LLM spawn path passes the CH-6 prompt gate (#9734).

Extends the ADR-0055 spawn-containment mechanism (``tests/_spawn_audit.py``,
the WS-2.2 telemetry ratchet) to the data-governance gate: prompts for
classified (``regulated-*``) repos must be redacted/blocked BEFORE any spawn,
so every module allowed to spawn an LLM must route its prompt through
``prompt_gate.gate_prompt`` (or the redaction-only ``gate_context_fields``
for assembly seams).

SCOPE OF THE GUARANTEE: like the telemetry ratchet, this is a containment
check over known spawn primitives + the hand-rolled-argv heuristic. It fails
closed when a new spawner appears without a gate call; it cannot prove the
gate call dominates every code path — the wiring tests
(``tests/test_prompt_gate_wiring.py``) pin the actual behavior per seam.

``_NAMED_GAPS`` mirrors the telemetry ``_GRANDFATHERED`` list: spawners with
no ``HydraFlowConfig`` in reach today. They MUST shrink toward empty and MUST
NOT grow.
"""

from __future__ import annotations

import ast

from tests._spawn_audit import SRC, iter_module_facts

# Raw LLM-spawn primitives (kept in sync with the telemetry ratchet via
# test_gate_seams_cover_all_telemetry_spawn_seams below).
_RAW_PRIMITIVES = frozenset({"stream_claude_process", "build_lightweight_command"})

# The gate entry points. A spawn seam must call one of these.
_GATE_CALLS = frozenset({"gate_prompt", "gate_context_fields"})

# Spawn seams (rel paths) that are approved to call the raw primitives AND
# therefore must consult the gate before spawning.
_GATED_SPAWN_SEAMS = frozenset(
    {
        "runner_utils.py",  # run_lightweight_agent + stream_claude_with_telemetry
        "base_runner.py",  # BaseRunner._execute
        "runners/base_subprocess_runner.py",  # BaseSubprocessRunner.run
    }
)

# Assembly seams: no backend in scope, redaction-only gate.
_ASSEMBLY_SEAMS = frozenset(
    {
        "preflight/context.py",  # gather_context
    }
)

# Named gaps (rel paths): known spawners that cannot gate yet because no
# HydraFlowConfig reaches their constructor (same blocker as their telemetry
# grandfathering). Ratchet: MUST shrink toward empty, MUST NOT grow.
_NAMED_GAPS = frozenset(
    {
        "term_proposer_runtime.py",  # ClaudeCLIClient has no config field
        "adversarial_agent_runner.py",  # SubprocessAgentRunner @dataclass, no config
    }
)


def test_every_gated_seam_calls_the_gate() -> None:
    """Each approved spawn/assembly seam must actually call the gate."""
    facts = {f.rel: f for f in iter_module_facts()}
    for rel in sorted(_GATED_SPAWN_SEAMS | _ASSEMBLY_SEAMS):
        assert rel in facts, f"gated seam {rel} not found in src/"
        assert facts[rel].calls & _GATE_CALLS, (
            f"{rel} is an approved LLM spawn/assembly seam but no longer calls "
            f"the CH-6 prompt gate ({sorted(_GATE_CALLS)}). Classified-repo "
            "prompts would leave the process unredacted/unblocked — call "
            "prompt_gate.gate_prompt before the spawn (fail closed)."
        )


def test_no_spawner_bypasses_the_gated_seams() -> None:
    """A module spawning outside the gated seams must be a named gap."""
    offenders: set[str] = set()
    for facts in iter_module_facts():
        if facts.rel in _GATED_SPAWN_SEAMS:
            continue
        bypasses_primitive = bool(facts.calls & _RAW_PRIMITIVES)
        hand_rolled_argv = "run_simple" in facts.calls and facts.has_agent_argv
        if bypasses_primitive or hand_rolled_argv:
            offenders.add(facts.rel)
    unexpected = sorted(offenders - _NAMED_GAPS)
    assert not unexpected, (
        "These modules spawn an LLM without routing through a gate-consulting "
        f"seam: {unexpected}. For classified repos their prompts would bypass "
        "CH-6 redaction/backend policy. Route the spawn through "
        "run_lightweight_agent / stream_claude_with_telemetry (or subclass "
        "BaseRunner/BaseSubprocessRunner), which call prompt_gate.gate_prompt "
        "— or, if truly impossible, add a named gap here AND to the CH-6 "
        "report (the list must never grow silently)."
    )
    stale = sorted(_NAMED_GAPS - offenders)
    assert not stale, (
        f"_NAMED_GAPS has stale entries that no longer spawn around the gate: "
        f"{stale}. Remove them — the ratchet is already satisfied there."
    )


# Runner modules whose ``self._execute(...)`` call sites all have a task/issue
# (or threaded label context) in scope. Every call MUST pass ``issue_labels=``
# so the CH-6 upward-only ``data-class:`` label elevation reaches the gate —
# omitting it silently disables label-based elevation for that spawn.
_RUNNER_EXECUTE_MODULES = (
    "agent.py",
    "planner.py",
    "research_runner.py",
    "reviewer.py",
    "hitl_runner.py",
)


def test_every_runner_execute_call_passes_issue_labels() -> None:
    """Each ``self._execute(...)`` in a runner module passes ``issue_labels=``.

    ``BaseRunner._execute`` feeds *issue_labels* into ``gate_prompt``'s
    upward-only data-class elevation. A call site that omits the kwarg makes
    the gate see only the repo-declared class, so a ``data-class:regulated-*``
    issue label on an internal repo would NOT redact/block that spawn. This
    pin makes the omission structurally impossible to reintroduce (#9734
    review finding 1).
    """
    offenders: list[str] = []
    for rel in _RUNNER_EXECUTE_MODULES:
        path = SRC / rel
        assert path.exists(), f"runner module {rel} not found in src/"
        tree = ast.parse(path.read_text(), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_self_execute = (
                isinstance(func, ast.Attribute)
                and func.attr == "_execute"
                and isinstance(func.value, ast.Name)
                and func.value.id == "self"
            )
            if not is_self_execute:
                continue
            if not any(kw.arg == "issue_labels" for kw in node.keywords):
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        f"These self._execute(...) call sites omit issue_labels=: {offenders}. "
        "Without it the CH-6 gate cannot apply the upward-only "
        "data-class:<class> label elevation for that spawn — pass "
        "issue_labels=task.tags / issue.tags / issue.labels (or thread the "
        "labels into the enclosing method) at every call."
    )


def test_gate_seams_cover_all_telemetry_spawn_seams() -> None:
    """Stay in lockstep with the WS-2.2 telemetry containment ratchet.

    Every telemetry-approved spawn seam must be a gated seam and every
    telemetry-grandfathered spawner must be a named gap here — so adding a
    new spawn seam to the telemetry ratchet without gating it fails THIS
    test until the gate is wired.
    """
    from tests.test_telemetry_source_completeness import (
        _APPROVED,
        _GRANDFATHERED,
    )

    assert _APPROVED <= _GATED_SPAWN_SEAMS, (
        "telemetry-approved spawn seams missing from the CH-6 gate ratchet: "
        f"{sorted(_APPROVED - _GATED_SPAWN_SEAMS)}. Wire prompt_gate.gate_prompt "
        "into the new seam and add it to _GATED_SPAWN_SEAMS."
    )
    assert _GRANDFATHERED <= _NAMED_GAPS, (
        "telemetry-grandfathered spawners missing from _NAMED_GAPS: "
        f"{sorted(_GRANDFATHERED - _NAMED_GAPS)}."
    )
