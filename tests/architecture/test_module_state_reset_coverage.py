"""Audit + ratchet: module-global mutable state must declare test-reset coverage (#10889).

Issue #10874 fixed the *wrong-alias* failure mode; this closes the follow-on gap:
module-level mutable state (container caches, lock registries, and custom-object
singletons) that is written at runtime can leak across tests under
``-n auto --dist loadscope`` (non-deterministic worker scheduling). Every such
global must have a *declared disposition* — a reset fixture, a documented reason
the leak is harmless, or a note that it is tracked debt awaiting a fixture. A new
ungoverned global added to ``src/`` fails this guard until it is classified.

Two candidate shapes are scanned: (1) module bindings to a mutable *container*
(``{}``/``[]``/``set()``/factory) that is runtime-mutated, and (2) module
bindings to an instance of a locally-defined *non-frozen* class — the idiomatic
``_X = SomeClass()`` singleton whose attributes/internal state get mutated,
possibly from another module (so it is flagged by shape, not by proven mutation;
``@dataclass(frozen=True)`` instances are immutable and excluded).

This is the ratchet, not the burn-down: the ``debt:`` entries below are the
honest current gap (only 4 of 25 have reset coverage today). Adding their reset
fixtures is follow-up work; this guard makes the inventory durable and stops it
growing silently.
"""

from __future__ import annotations

import ast
import pathlib

_SRC = pathlib.Path(__file__).resolve().parent.parent.parent / "src"

# Mutable-container factories whose module-level binding is reset-sensitive.
_FACTORY = {
    "dict",
    "list",
    "set",
    "defaultdict",
    "OrderedDict",
    "deque",
    "Counter",
    "WeakValueDictionary",
    "WeakKeyDictionary",
}
# In-place mutation methods that mark a container as runtime-written.
_MUT_METHODS = {
    "append",
    "extend",
    "insert",
    "add",
    "update",
    "pop",
    "popitem",
    "clear",
    "setdefault",
    "remove",
    "discard",
    "appendleft",
    "popleft",
}

#: Every detected mutable module global → its test-reset disposition. Keyed on
#: ``<src-relative-path>::<name>`` (line-number-free so it survives edits).
#:   reset:<fixture>   — a *function-scoped* autouse conftest fixture clears it every test
#:   harmless:<reason> — cross-test leakage is provably benign (or state is effectively immutable)
#:   debt:<note>       — no per-test reset yet; tracked burn-down (#10889)
_DISPOSITION: dict[str, str] = {
    # --- covered today (3) ---
    "src/subprocess_util.py::_gh_semaphore": "reset:_reset_gh_semaphore",
    "src/subprocess_util.py::_rate_limit_until": "reset:_reset_gh_semaphore",
    "src/subprocess_util.py::_gh_circuit_breaker": "reset:_reset_gh_semaphore (reset_gh_circuit_breaker)",
    "src/credit_failover.py::_state": "reset:_reset_credit_failover",
    "src/prompt_telemetry.py::_HEALTH_STATE": "reset:_reset_prompt_telemetry_health_state",
    # --- harmless (effectively immutable, import-time-only, or caller-paired) ---
    "src/config.py::_ENV_INT_OVERRIDES": "harmless:import-time-only += (config.py) appending give-up-window overrides; never mutated during a run",
    "src/config.py::_DOTENV_INERT_ROOTS": "harmless:session-scoped registration of the default repo root; extra register_dotenv_inert_root calls must be unregister-paired by the caller (test_dotenv_inert_under_pytest_10902.py), not reset per-test",
    "src/events.py::_event_counter": "harmless:monotonic event-id counter; tests never assert absolute IDs (docs/wiki/testing.md), so leak is benign by convention",
    # --- tracked debt: no per-test reset fixture yet ---
    "src/knowledge_metrics.py::metrics": "debt:mutable metrics accumulator (increment/reset); has .reset() but no autouse fixture calls it",
    "src/agent_rate_backoff.py::_BACKOFF": "debt:rate-backoff singleton; no autouse reset, touching tests pair try/finally manually",
    "src/subprocess_util.py::_shadow_sampler": "debt:shadow-corpus sampler; repopulated per call, leak low-risk",
    "src/adr_utils.py::_assigned_adr_numbers": "debt:ADR-number allocator cache; leak could mask a collision test",
    "src/plugin_skill_registry.py::_skill_cache": "debt:skill discovery cache; leak could serve stale skills",
    "src/corpus_learning_loop.py::_HEADER_RE_CACHE": "debt:compiled-regex cache; content-keyed, leak low-risk",
    "src/file_util.py::_thread_gate_registry": "debt:per-path thread gates; leak could cross-wire concurrency tests",
    "src/process_group.py::_TRACKED": "debt:tracked subprocess PGIDs; leak could reap across tests",
    "src/workspace.py::_FETCH_LOCKS": "debt:per-repo fetch locks; leak holds stale asyncio.Lock",
    "src/workspace.py::_WORKTREE_LOCKS": "debt:per-worktree locks; leak holds stale asyncio.Lock",
    "src/git_revision.py::_BOOT_SHA_SLOT": "debt:boot-SHA memo; leak pins a stale SHA across tests",
    "src/trace_collector.py::_ACTIVE_CONFIG_SLOT": "debt:active-config slot; leak points at a torn-down config",
    "src/event_loop_watchdog.py::_ACTIVE_SLOT": "debt:watchdog active slot; leak could mis-attribute a stall",
    "src/prompt_observatory.py::_COUNTERS": "debt:prompt counters; leak inflates cross-test tallies",
    "src/dashboard_routes/_hitl_routes.py::_pending_warm_tasks": "debt:HITL warm tasks; leak holds torn-down tasks",
    "src/dashboard_routes/_trust_routes.py::_ANOMALY_CACHE": "debt:trust anomaly cache; leak serves stale rows",
    "src/dashboard_routes/_trust_routes.py::_ESCAPE_CACHE": "debt:escape cache; leak serves stale rows",
    "src/execution.py::_default_runner": "debt:lazy default-runner singleton; leak pins a stale runner",
}


def _mutable_binding(node: ast.expr | None) -> bool:
    if isinstance(node, ast.Dict | ast.List | ast.Set):
        return True
    if isinstance(node, ast.Constant) and node.value is None:
        return True  # lazy singleton, reassigned under `global`
    if isinstance(node, ast.Call):
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else func.attr
            if isinstance(func, ast.Attribute)
            else None
        )
        return name in _FACTORY
    return False


def _is_frozen_dataclass(cls: ast.ClassDef) -> bool:
    for dec in cls.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        func = dec.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name != "dataclass":
            continue
        for kw in dec.keywords:
            if (
                kw.arg == "frozen"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
            ):
                return True
    return False


def _module_candidates(tree: ast.Module) -> dict[str, str]:
    """``name -> kind`` where kind is ``'container'`` or ``'singleton'``.

    container: a mutable container literal/factory (reset-sensitive only if
      runtime-mutated). singleton: an instance of a locally-defined *non-frozen*
      class — reset-sensitive by shape (mutation may be cross-module).
    """
    classdefs = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    frozen = {name for name, cls in classdefs.items() if _is_frozen_dataclass(cls)}
    out: dict[str, str] = {}
    for node in tree.body:
        pairs: list[tuple[ast.Name, ast.expr | None]] = []
        if isinstance(node, ast.Assign):
            pairs = [(t, node.value) for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            pairs = [(node.target, node.value)]
        for target, value in pairs:
            if _mutable_binding(value):
                out[target.id] = "container"
            elif (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id in classdefs
                and value.func.id not in frozen
            ):
                out[target.id] = "singleton"
    return out


def _runtime_mutated_names(tree: ast.Module) -> set[str]:
    mutated: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Store | ast.Del)
            and isinstance(node.value, ast.Name)
        ):
            mutated.add(node.value.id)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            mutated.add(node.target.id)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _MUT_METHODS
            and isinstance(node.func.value, ast.Name)
        ):
            mutated.add(node.func.value.id)
    # Singletons: reassigned via `global name` inside a function.
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            declared = {
                n for g in ast.walk(fn) if isinstance(g, ast.Global) for n in g.names
            }
            for inner in ast.walk(fn):
                if (
                    isinstance(inner, ast.Name)
                    and isinstance(inner.ctx, ast.Store)
                    and inner.id in declared
                ):
                    mutated.add(inner.id)
    return mutated


def discover_mutable_module_state() -> set[str]:
    """``<src-relative-path>::<name>`` for every runtime-mutated module global."""
    found: set[str] = set()
    for path in sorted(_SRC.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        candidates = _module_candidates(tree)
        if not candidates:
            continue
        mutated = _runtime_mutated_names(tree)
        rel = path.relative_to(_SRC.parent).as_posix()
        for name, kind in candidates.items():
            # singletons are reset-sensitive by shape; containers only if mutated.
            if kind == "singleton" or name in mutated:
                found.add(f"{rel}::{name}")
    return found


def test_every_mutable_module_global_has_a_declared_disposition() -> None:
    found = discover_mutable_module_state()
    undeclared = sorted(found - _DISPOSITION.keys())
    assert not undeclared, (
        "New runtime-mutated module global(s) under src/ with no declared "
        "test-reset disposition (#10889). Add a reset fixture and mark "
        f"'reset:', document 'harmless:', or record 'debt:' in _DISPOSITION: {undeclared}"
    )


def test_disposition_registry_has_no_stale_entries() -> None:
    found = discover_mutable_module_state()
    stale = sorted(_DISPOSITION.keys() - found)
    assert not stale, (
        "_DISPOSITION lists module state the detector no longer finds — the "
        f"global was removed or renamed; drop the entry: {stale}"
    )


def test_reset_dispositions_name_a_real_conftest_fixture() -> None:
    # Keep 'reset:' claims honest — the named fixture/function must exist.
    conftest = (_SRC.parent / "tests" / "conftest.py").read_text(encoding="utf-8")
    missing = []
    for key, disp in _DISPOSITION.items():
        if disp.startswith("reset:"):
            fixture = disp.split(":", 1)[1].split(" ", 1)[0]
            if f"def {fixture}" not in conftest:
                missing.append(f"{key} -> {fixture}")
    assert not missing, (
        f"reset: disposition names a fixture not in conftest.py: {missing}"
    )
