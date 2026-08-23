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
from pathlib import Path

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

# This recorder's prompt is the internal constant ``"ping"`` and contains no
# repo/user content to classify. ContractRefreshLoop disables the legacy host
# subprocess in the terminal profile because environment scrubbing cannot hide
# host OAuth/keychain state.
_FIXED_PROMPT_SPAWN_EXEMPT = frozenset({"contract_recording.py"})

# Assembly seams: no backend in scope, redaction-only gate.
_ASSEMBLY_SEAMS = frozenset(
    {
        "preflight/context.py",  # gather_context
    }
)

# Named gaps (rel paths): known spawners that cannot gate yet because no
# HydraFlowConfig reaches their constructor (same blocker as their telemetry
# grandfathering). Ratchet: MUST shrink toward empty, MUST NOT grow.
_NAMED_GAPS = frozenset()


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
        if facts.rel in _GATED_SPAWN_SEAMS or facts.rel in _FIXED_PROMPT_SPAWN_EXEMPT:
            continue
        bypasses_primitive = bool(facts.calls & _RAW_PRIMITIVES)
        hand_rolled_argv = "run_simple" in facts.calls and facts.has_agent_argv
        raw_agent_spawn = (
            facts.has_agent_inference_argv and facts.has_raw_subprocess_run
        )
        if bypasses_primitive or hand_rolled_argv or raw_agent_spawn:
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


# Runner modules are DERIVED from the BaseRunner subclass set (#10000): the
# old hand-maintained tuple listed 5 of 12 subclass modules, so more than
# half the runner surface silently bypassed the pin. Every ``self._execute``
# call in a derived module MUST pass ``issue_labels=`` so the CH-6
# upward-only ``data-class:`` label elevation reaches the gate — omitting it
# silently disables label-based elevation for that spawn.

# Interface-gap exemptions from the runner pin below. Mirrors the
# implement_spec_reviewer.py precedent for _AGENTPORT_CALLER_FOLLOWUPS: an
# entry means the module's enclosing interfaces verifiably carry no issue
# context, and threading labels is an interface change tracked as a named
# follow-up issue — never a silent skip. Currently empty: every BaseRunner
# subclass has (or is threaded) label context at its _execute call sites.
_RUNNER_EXECUTE_EXEMPT: tuple[str, ...] = ()


def _runner_source_files(src_dir: Path) -> list[Path]:
    """Top-level ``*.py`` plus every file of a top-level package.

    A runner that outgrows one file becomes a package (``src/agent/``, the mass
    roster shape — #11547). ``src_dir.glob("*.py")`` stops seeing it, and every
    ``self._execute`` call site inside it drops out of this pin. Walking the
    package keeps the scan on the code rather than on a filename.
    """
    files = list(src_dir.glob("*.py"))
    for pkg in sorted(src_dir.iterdir()):
        if pkg.is_dir() and (pkg / "__init__.py").is_file():
            # ``rglob``, not ``glob``: the docstring above names the
            # ``glob("*.py")`` hazard but the fix only went one level deep, so a
            # sub-package (``src/agent/skills/*.py``) still dropped out (#11673).
            files.extend(pkg.rglob("*.py"))
    return sorted(files)


def _base_runner_modules(src_dir: Path = SRC) -> tuple[str, ...]:
    """Enumerate ``src/`` modules defining a BaseRunner subclass, ``src``-relative.

    AST-derived (``class X(BaseRunner)`` / ``class X(mod.BaseRunner)``) so the
    module list can never rot the way the hand-maintained tuple did (#10000).
    Paths are ``src``-relative POSIX strings so a decomposed runner reports
    ``agent/_quality.py``, not a bare basename that could collide.
    """
    modules: list[str] = []
    for path in _runner_source_files(src_dir):
        tree = ast.parse(path.read_text(), filename=path.name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {
                getattr(base, "id", None) or getattr(base, "attr", None)
                for base in node.bases
            }
            if "BaseRunner" in bases:
                modules.append(path.relative_to(src_dir).as_posix())
                break
    return tuple(modules)


def _unlabeled_execute_calls(path: Path, rel: str) -> list[str]:
    """Return ``rel:lineno`` for every ``self._execute(...)`` in *path* that
    omits the ``issue_labels=`` kwarg."""
    offenders: list[str] = []
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
    return offenders


def test_every_runner_execute_call_passes_issue_labels() -> None:
    """Each ``self._execute(...)`` in a runner module passes ``issue_labels=``.

    ``BaseRunner._execute`` feeds *issue_labels* into ``gate_prompt``'s
    upward-only data-class elevation. A call site that omits the kwarg makes
    the gate see only the repo-declared class, so a ``data-class:regulated-*``
    issue label on an internal repo would NOT redact/block that spawn. This
    pin makes the omission structurally impossible to reintroduce (#9734
    review finding 1) — and the module list is derived from the BaseRunner
    subclass set so a new runner is covered the moment it exists (#10000).
    """
    modules = _base_runner_modules()
    # Sanity floor: if derivation ever breaks the pin must not pass vacuously.
    # ``agent/`` is a package (#11547 batch 4): its BaseRunner-derived slices
    # are where the ``self._execute`` call sites live, so the floor names the
    # files, not the old ``agent.py`` basename.
    core = {
        "agent/_runner.py",
        "agent/_prequality.py",
        "agent/_quality.py",
        "agent/_skills.py",
        "planner.py",
        "reviewer.py",
        "triage.py",
    }
    assert core <= set(modules), (
        f"BaseRunner subclass derivation lost core runner modules: "
        f"{sorted(core - set(modules))} — _base_runner_modules is broken."
    )
    stale_exempt = sorted(set(_RUNNER_EXECUTE_EXEMPT) - set(modules))
    assert not stale_exempt, (
        f"_RUNNER_EXECUTE_EXEMPT has stale entries that are no longer "
        f"BaseRunner subclass modules: {stale_exempt}. Remove them."
    )
    offenders: list[str] = []
    for rel in modules:
        if rel in _RUNNER_EXECUTE_EXEMPT:
            continue
        offenders.extend(_unlabeled_execute_calls(SRC / rel, rel))
    assert not offenders, (
        f"These self._execute(...) call sites omit issue_labels=: {offenders}. "
        "Without it the CH-6 gate cannot apply the upward-only "
        "data-class:<class> label elevation for that spawn — pass "
        "issue_labels=task.tags / issue.tags / issue.labels (or thread the "
        "labels into the enclosing method) at every call. If the enclosing "
        "interface truly carries no issue context, add the module to "
        "_RUNNER_EXECUTE_EXEMPT with a comment naming the follow-up issue."
    )


_AGENTPORT_CALLER_MODULES = (
    "merge_conflict_resolver.py",
    "pr_unsticker.py",
)

# implement_spec_reviewer.py also calls self._agents.execute but its run()
# interface carries no issue context at all — threading labels there is an
# interface change tracked as a named follow-up, not silently exempted.
_AGENTPORT_CALLER_FOLLOWUPS = ("implement_spec_reviewer.py",)


def test_every_agentport_execute_call_passes_issue_labels() -> None:
    """Each ``self._agents.execute(...)`` protocol call passes ``issue_labels=``.

    The runner-module pin above walks ``self._execute`` (the BaseRunner
    internal); infrastructure modules invoke the SAME gate through the
    AgentPort protocol as ``self._agents.execute`` — the convergence review
    found four such call sites (conflict resolution, PR unsticking) where a
    regulated issue label silently lost its elevation. This pin closes that
    structural blind spot.
    """
    offenders: list[str] = []
    for rel in _AGENTPORT_CALLER_MODULES:
        path = SRC / rel
        assert path.exists(), f"module {rel} not found in src/"
        tree = ast.parse(path.read_text(), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_agents_execute = (
                isinstance(func, ast.Attribute)
                and func.attr == "execute"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "_agents"
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == "self"
            )
            if not is_agents_execute:
                continue
            if not any(kw.arg == "issue_labels" for kw in node.keywords):
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        f"These self._agents.execute(...) call sites omit issue_labels=: "
        f"{offenders}. Pass issue_labels=issue.tags / issue.labels so the "
        "CH-6 gate can apply per-issue data-class elevation."
    )


# ---------------------------------------------------------------------------
# run_lightweight_agent callers (CH-6 convergence review finding 1)
# ---------------------------------------------------------------------------

# ``run_lightweight_agent`` callers VERIFIED label-free: no issue object (and
# therefore no labels) exists anywhere in the enclosing call chain, so there
# is no per-issue ``data-class:<class>`` elevation to thread. The
# repo-registry data class still gates these spawns. Each entry documents WHY
# it is exempt — an undocumented module must thread ``issue_labels=``.
_LIGHTWEIGHT_LABEL_FREE_CALLERS = frozenset(
    {
        # Council-reviews ADR *files*: review_proposed_adrs() walks
        # docs/adr/*.md in the repo checkout. No GitHub issue appears
        # anywhere in the chain (the prompt is built from ADR file content),
        # so only the repo-declared class applies.
        "adr_reviewer.py",
    }
)

# Callers whose chain carries a bare ``issue_number`` int but no issue
# object/labels: threading requires an interface change through the phase
# facades (``synthesize_ingest`` and six sibling ``_call_model`` flows).
# Named follow-up, not a silent exemption — mirrors
# ``_AGENTPORT_CALLER_FOLLOWUPS`` above.
_LIGHTWEIGHT_LABEL_FOLLOWUPS = frozenset({"wiki_compiler.py"})


def test_every_run_lightweight_agent_call_passes_issue_labels() -> None:
    """Each ``run_lightweight_agent(...)`` call site passes ``issue_labels=``.

    ``run_lightweight_agent`` feeds *issue_labels* into ``gate_prompt``'s
    upward-only data-class elevation, exactly like the sibling seams
    (``BaseRunner._execute``, ``stream_claude_with_telemetry``). A call site
    that omits the kwarg makes the gate see only the repo-declared class, so
    a ``data-class:regulated-*`` label on an issue would NOT redact/block
    that spawn (#9734 convergence review finding 1). Callers verified
    label-free are allowlisted above with the reason.
    """
    offenders: list[str] = []
    exempt = _LIGHTWEIGHT_LABEL_FREE_CALLERS | _LIGHTWEIGHT_LABEL_FOLLOWUPS
    callers: set[str] = set()
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel == "runner_utils.py":
            continue  # the seam definition itself
        tree = ast.parse(path.read_text(), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            else:
                continue
            if name != "run_lightweight_agent":
                continue
            callers.add(rel)
            if rel in exempt:
                continue
            if not any(kw.arg == "issue_labels" for kw in node.keywords):
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        f"These run_lightweight_agent(...) call sites omit issue_labels=: "
        f"{offenders}. Without it the CH-6 gate cannot apply the upward-only "
        "data-class:<class> label elevation for that spawn — thread the "
        "enclosing issue's labels (issue.labels / issue.tags / task.tags) "
        "down to the call, or, if the chain verifiably has no issue in "
        "scope, add a documented allowlist entry explaining why."
    )
    stale = sorted(exempt - callers)
    assert not stale, (
        f"Label-free allowlist has stale entries that no longer call "
        f"run_lightweight_agent: {stale}. Remove them."
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
