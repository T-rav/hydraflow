"""Class-level recurrence guard for #11416's silent-omission shape.

A catalog builder that accepts a port key but never forwards it to the loop
constructor leaves an *optional* collaborator permanently ``None`` — the
loop instantiates fine (so ``test_loop_instantiation.py`` stays green) but a
whole phase gated on ``self._collaborator is not None`` goes quietly
unreachable in every MockWorld scenario. ``_build_repo_wiki`` had exactly
this shape for ``wiki_compiler`` (silently gating Phase 2/8 compilation).

Rather than a hardcoded table of (loop, collaborators) rows — which only
guards whatever a human happened to enumerate — this derives the universe
of checks from the loop classes themselves:

1. Every builder in ``_BUILDERS`` is AST-read to find the ``Call`` that
   constructs and returns its loop, and which kwargs that call passes.
2. ``inspect.signature`` on the resolved loop class finds every
   constructor param whose default is ``None`` (an *optional* collaborator).
3. A param missing from the builder's forwarded kwargs is a violation
   unless ``(loop_name, param_name)`` is in ``_ALLOWLIST`` with a reason.

The allowlist is self-retiring: ``test_allowlist_entries_are_still_needed``
fails if a builder starts forwarding a param (or a loop drops it), so a
listed entry doesn't quietly outlive its reason.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import pytest

from tests.scenarios.catalog import loop_registrations
from tests.scenarios.catalog.loop_registrations import _BUILDERS

# (loop_name, param_name) -> why this None-default constructor param is
# intentionally left unforwarded by its builder. Every entry was audited
# against the loop's own None-handling (does it silently build a real,
# side-effecting collaborator, or genuinely no-op?) — see #11416.
_ALLOWLIST: dict[tuple[str, str], str] = {
    # bg_workers is injected post-construction via loop.set_bg_workers(...),
    # matching production orchestrator wiring (src/orchestrator.py) — it is
    # never a constructor kwarg, by design.
    ("goal_supervisor", "bg_workers"): (
        "set via loop.set_bg_workers(...) post-construction, matching "
        "production orchestrator wiring — not a constructor kwarg"
    ),
    ("trust_fleet_sanity", "bg_workers"): (
        "set via loop.set_bg_workers(...) post-construction, matching "
        "production orchestrator wiring — not a constructor kwarg"
    ),
    ("health_monitor", "bg_workers"): (
        "set via loop.set_bg_workers(...) post-construction, matching "
        "production orchestrator wiring — not a constructor kwarg"
    ),
    # Pure metrics sinks / no-fallback-construction params: the loop no-ops
    # when unset rather than lazily building a real, side-effecting
    # collaborator, so an unforwarded port causes no live side effect.
    ("health_monitor", "retrospective_queue"): (
        "no fallback construction (`if self._retrospective_queue is not "
        "None`) — feature no-ops when unset, no live side effect"
    ),
    ("health_monitor", "observability"): (
        "pure metrics sink with no fallback construction when None, no live side effect"
    ),
    ("stale_issue", "observability"): (
        "pure metrics sink with no fallback construction when None, no live side effect"
    ),
    ("workspace_gc", "is_in_pipeline_cb"): (
        "optional callback with no fallback construction when None, no live side effect"
    ),
    ("log_ingest", "dedup"): (
        "falls back to an empty in-memory set (`dedup.get() if dedup else "
        "set()`) when unset, no live side effect"
    ),
    ("live_corpus_replay", "dispatchers"): (
        "falls back to an empty dict when unset, no live side effect"
    ),
    ("disturbance_dampener", "dimensions"): (
        "falls back to the module-level DIMENSIONS constant when unset — "
        "pure config default, no live side effect"
    ),
    ("corpus_learning", "state"): (
        "the loop's own docstring documents state as optional-for-tests; "
        "every use is hasattr/None-guarded with no fallback construction"
    ),
    ("pr_red_repair", "runner"): (
        "no fallback construction — `if runner is None: return "
        '"skipped_no_runner"` no-ops, no live side effect'
    ),
    # Credentials() fallbacks are a pure pydantic default (empty gh_token),
    # not an I/O side effect.
    ("health_monitor", "credentials"): (
        "falls back to Credentials() — empty gh_token pydantic default, "
        "no I/O side effect"
    ),
    ("workspace_gc", "credentials"): (
        "falls back to Credentials() — empty gh_token pydantic default, "
        "no I/O side effect"
    ),
    ("report_issue", "credentials"): (
        "falls back to Credentials() — empty gh_token pydantic default, "
        "no I/O side effect"
    ),
    ("repo_wiki", "credentials"): (
        "no fallback construction — push path is skipped when unset "
        "(`if self._credentials is None or not self._credentials.gh_token`), "
        "no live side effect"
    ),
    ("repo_wiki", "maintenance_queue"): (
        "falls back to an in-memory MaintenanceQueue() when unset, no live side effect"
    ),
    ("pr_red_repair", "human_pr_dedup"): (
        "falls back to a real DedupStore rooted at config.data_root — "
        "writes only within the scenario's own tmp data root, "
        "no external side effect"
    ),
    # Pre-existing gaps predating #11416 that DO build a real,
    # side-effecting collaborator when unset. Same shape as the
    # wiki_compiler/refine_llm/auto_diagnoser/workspaces fixes in #11416,
    # but not part of that fix's scope — flagged here rather than silently
    # dropped so a future pass has a precise, audited list to work from.
    ("report_issue", "runner"): (
        "passed straight to stream_claude_with_telemetry(); production "
        "fallback there spawns a real subprocess runner. Pre-existing "
        "gap, out of scope for #11416"
    ),
    ("disturbance_dampener", "pr_opener"): (
        "falls back to generate_and_open_pr_async, a real PR-opening "
        "coroutine. Pre-existing gap, out of scope for #11416"
    ),
    ("fitness_scorecard", "repo_root"): (
        "falls back to Path.cwd() when unset, reading outside the "
        "scenario's tmp root. Pre-existing gap, out of scope for #11416"
    ),
    ("sampled_audit", "adjudicator"): (
        "production fallback lazily builds _CLIAdjudicatorLLM (real "
        "subprocess), spawned only when both "
        "sampled_audit_auto_adjudicate_enabled and "
        "sampled_audit_reaudit_enabled are set (scenario configs default "
        "both off). Pre-existing gap, out of scope for #11416"
    ),
}


def _local_imports(fn_node: ast.FunctionDef) -> dict[str, str]:
    """Map names imported inside ``fn_node`` to their source module."""
    mapping: dict[str, str] = {}
    for node in ast.walk(fn_node):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                mapping[alias.asname or alias.name] = node.module
    return mapping


def _call_assignments(fn_node: ast.FunctionDef) -> dict[str, ast.Call]:
    """Map ``name = SomeCall(...)`` targets to their ``Call`` node."""
    assigns: dict[str, ast.Call] = {}
    for node in ast.walk(fn_node):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigns[target.id] = node.value
    return assigns


def _loop_constructor_call(fn_node: ast.FunctionDef) -> ast.Call | None:
    """Find the ``Call`` that builds the loop this builder returns.

    Builders either ``return SomeLoop(...)`` directly, or assign it to a
    variable (``loop = SomeLoop(...)``) and ``return loop`` after further
    mutation (e.g. ``loop.set_bg_workers(...)``).
    """
    assigns = _call_assignments(fn_node)
    for node in ast.walk(fn_node):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        value = node.value
        if isinstance(value, ast.Call):
            return value
        if isinstance(value, ast.Name) and value.id in assigns:
            return assigns[value.id]
    return None


def _resolve_loop_class(fn_node: ast.FunctionDef, call: ast.Call) -> type:
    assert isinstance(call.func, ast.Name), (
        f"loop constructor call isn't a plain Name call: {ast.dump(call.func)}"
    )
    class_name = call.func.id
    module_name = _local_imports(fn_node).get(class_name)
    assert module_name is not None, (
        f"couldn't find a local import for {class_name!r} in "
        f"{fn_node.name!r} — the guard assumes builders locally import "
        "their loop class"
    )
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def _none_default_params(loop_cls: type) -> list[str]:
    sig = inspect.signature(loop_cls)
    return [
        p.name
        for p in sig.parameters.values()
        if p.default is None and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
    ]


def _wiring_cases() -> list[tuple[str, str, set[str], list[str]]]:
    """One row per registered loop: its name, class, forwarded kwargs, and
    the loop's own None-default (optional) constructor params."""
    sourcefile = inspect.getsourcefile(loop_registrations)
    assert sourcefile is not None, "loop_registrations has no source file"
    tree = ast.parse(Path(sourcefile).read_text())
    fn_nodes = {
        node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }

    cases: list[tuple[str, str, set[str], list[str]]] = []
    for loop_name, builder in sorted(_BUILDERS.items()):
        fn_node = fn_nodes.get(builder.__name__)
        assert fn_node is not None, (
            f"couldn't find the source of builder {builder.__name__!r} "
            f"for loop {loop_name!r}"
        )
        call = _loop_constructor_call(fn_node)
        assert call is not None, (
            f"{loop_name!r}: couldn't locate the Call that constructs and "
            "returns its loop"
        )
        loop_cls = _resolve_loop_class(fn_node, call)
        forwarded = {kw.arg for kw in call.keywords if kw.arg}
        cases.append(
            (loop_name, loop_cls.__name__, forwarded, _none_default_params(loop_cls))
        )
    return cases


@pytest.fixture(scope="module")
def wiring_cases() -> list[tuple[str, str, set[str], list[str]]]:
    return _wiring_cases()


def test_every_none_default_param_is_forwarded_or_allowlisted(
    wiring_cases: list[tuple[str, str, set[str], list[str]]],
) -> None:
    violations = []
    for loop_name, cls_name, forwarded, none_default in wiring_cases:
        for param in none_default:
            if param in forwarded:
                continue
            if (loop_name, param) in _ALLOWLIST:
                continue
            violations.append(
                f"{loop_name!r} ({cls_name}) does not forward {param!r} to "
                f"its constructor — either pass ports.get({param!r}) (or a "
                f"suitably named port key, e.g. {loop_name}_{param}) in "
                f"_build_{loop_name}, or add "
                f"('{loop_name}', {param!r}) to _ALLOWLIST with a reason."
            )
    assert not violations, (
        "Builders leaving optional collaborators unforwarded (#11416 "
        "shape):\n" + "\n".join(violations)
    )


def test_allowlist_entries_are_still_needed(
    wiring_cases: list[tuple[str, str, set[str], list[str]]],
) -> None:
    still_missing = {
        (loop_name, param)
        for loop_name, _cls_name, forwarded, none_default in wiring_cases
        for param in none_default
        if param not in forwarded
    }
    stale = sorted(key for key in _ALLOWLIST if key not in still_missing)
    assert not stale, (
        "Stale _ALLOWLIST entries — the param is now forwarded by its "
        f"builder, or the loop no longer accepts it. Remove: {stale}"
    )
