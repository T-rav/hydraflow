"""Which background loops are actually driven by a MockWorld scenario.

``docs/standards/testing/README.md`` is unambiguous:

    Every load-bearing feature in HydraFlow ships through three layers of
    tests before it merges. Skipping a layer is a procedural failure, not a
    judgment call. [...] **MockWorld scenarios catch integration bugs unit
    tests can't see.**

**Nothing enforced it.** The nearest existing gate,
``tests/scenarios/catalog/test_catalog_completeness.py``, requires every loop
in ``bg_loop_registry`` to have a *catalog builder* — which is not the same
claim. A builder is a construction recipe; it can sit in
``loop_registrations.py`` forever without one test ever calling it. "Has a
builder" and "is exercised through the loop" are two different questions, and
only the first one had an answer.

This module answers the second. A loop counts as covered when a scenario file
under ``tests/scenarios/`` does one of:

* **drives it through the catalog** — passes its registered key as a string
  literal to ``world.run_with_loops([...])`` (or ``LoopCatalog.instantiate``),
  the idiom 43 of the 64 loops use; or
* **constructs it directly** — calls the loop class itself, the idiom the
  other 21 use (``AdrConformanceLoop(...)`` in
  ``tests/scenarios/test_adr_conformance_e2e.py``).

Both are read from the AST, never from the file text. That distinction is
load-bearing: 32 loops are named in a scenario *docstring* and nowhere else
("MockWorld scenario for CharterDriftCaretakerLoop"), because the scenario
drives them by catalog key. A textual needle would score those as covered
whether or not the test body still touched them, and would go on scoring them
covered after the body was deleted. Prose is not coverage.

**The enumeration is borrowed, not rewritten.** :func:`loop_subjects` calls
``arch.extractors.loops.extract_loops`` — the same extractor that generates
``docs/arch/generated/loops.md`` — rather than globbing ``src/*_loop.py``. A
path glob is the failure this repo has hit eleven times (see
``src/path_membership.py``): the day a loop becomes a package, or lands in
``src/`` under a name without ``_loop`` in it, a glob quietly stops seeing it
and the gate goes green on a smaller world. ``extract_loops`` walks all of
``src/`` for ``BaseBackgroundLoop`` subclasses and already collapses a
decomposed loop package to its importable identity.

Lives under ``tests/architecture/`` beside ``sandbox_seam_scan``,
``subprocess_reap_scan`` and ``mixin_seam_scan`` — the repo's other structural
scanners.
"""

from __future__ import annotations

import ast
import textwrap
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

__all__ = [
    "REPO_ROOT",
    "LoopSubject",
    "builder_reachable_classes",
    "catalog_builder_keys",
    "covered_loops",
    "loop_subjects",
    "scenario_files",
    "uncovered_loops",
]

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Callables that take a loop's registered catalog key and run it. Scenarios
#: reach a catalogued loop through exactly these; a string literal in an
#: argument to one of them is a drive, anywhere else in the file it is prose.
_DRIVER_CALLS: frozenset[str] = frozenset({"run_with_loops", "instantiate", "run_loop"})


@dataclass(frozen=True)
class LoopSubject:
    """One ``BaseBackgroundLoop`` subclass held to the scenario requirement."""

    class_name: str
    """``CharterDriftCaretakerLoop``. The grandfather key — a class name
    survives the module→package decomposition that re-keys a path."""

    module: str
    """Dotted importable identity, e.g. ``src.charter_drift_caretaker_loop``."""

    source_path: str
    """Repo-relative path of the file declaring the class."""


# ---------------------------------------------------------------------------
# The subject
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def loop_subjects() -> tuple[LoopSubject, ...]:
    """Every ``BaseBackgroundLoop`` subclass in ``src/``, by class name.

    Delegates discovery to ``arch.extractors.loops.extract_loops`` — the
    generator behind ``docs/arch/generated/loops.md`` — so this gate and the
    published loop registry can never disagree about what a loop is.
    """
    from arch.extractors.loops import extract_loops

    subjects = [
        LoopSubject(
            class_name=info.name,
            module=info.module,
            source_path=info.module.replace(".", "/") + ".py",
        )
        for info in extract_loops(REPO_ROOT / "src")
    ]
    return tuple(sorted(subjects, key=lambda s: s.class_name))


@lru_cache(maxsize=1)
def scenario_files() -> tuple[Path, ...]:
    """Every MockWorld scenario module under ``tests/scenarios/``."""
    return tuple(sorted((REPO_ROOT / "tests" / "scenarios").rglob("test_*.py")))


# ---------------------------------------------------------------------------
# The catalog: key -> the loop class its builder constructs
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _key_to_classes() -> dict[str, frozenset[str]]:
    """Map each registered catalog key to the loop classes its builder builds.

    Read from the builder's own AST rather than by calling it: instantiating
    64 builders would need a live ``MockWorld``, and a builder that raises
    would silently drop its loop out of the map — a shrinking subject, which
    is the failure this file exists to make loud.
    """
    from tests.scenarios.catalog.loop_registrations import _BUILDERS

    known = {subject.class_name for subject in loop_subjects()}
    mapping: dict[str, frozenset[str]] = {}
    for key, builder in _BUILDERS.items():
        import inspect  # noqa: PLC0415 - only needed on this path

        try:
            tree = ast.parse(textwrap.dedent(inspect.getsource(builder)))
        except (OSError, TypeError, SyntaxError):  # pragma: no cover - defensive
            continue
        built = {
            name
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for name in (_called_name(node),)
            if name in known
        }
        if built:
            mapping[key] = frozenset(built)
    return mapping


def catalog_builder_keys() -> frozenset[str]:
    """Every key registered in the MockWorld loop catalog."""
    from tests.scenarios.catalog.loop_registrations import _BUILDERS

    return frozenset(_BUILDERS)


def builder_reachable_classes() -> frozenset[str]:
    """Loop classes reachable from a catalog builder.

    The independently maintained object this gate's subject is pinned
    against: ``loop_registrations.py`` is hand-written, so a loop that fell
    out of :func:`loop_subjects` is still named by its builder here.
    """
    return (
        frozenset().union(*_key_to_classes().values())
        if _key_to_classes()
        else frozenset()
    )


def _called_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


# ---------------------------------------------------------------------------
# The coverage question
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def covered_loops() -> dict[str, tuple[str, ...]]:
    """Loop class name -> the scenario files that drive it.

    Only loops with at least one driving scenario appear.
    """
    key_to_classes = _key_to_classes()
    known = {subject.class_name for subject in loop_subjects()}
    found: dict[str, set[str]] = {}

    for path in scenario_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - defensive
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = _called_name(node)
            # (a) direct construction of the loop class
            if called in known:
                found.setdefault(called, set()).add(rel)
            # (b) driven through the catalog by its registered key
            if called in _DRIVER_CALLS:
                arguments = [*node.args, *(kw.value for kw in node.keywords)]
                for argument in arguments:
                    for literal in ast.walk(argument):
                        if not (
                            isinstance(literal, ast.Constant)
                            and isinstance(literal.value, str)
                        ):
                            continue
                        for cls in key_to_classes.get(literal.value, ()):
                            found.setdefault(cls, set()).add(rel)

    return {name: tuple(sorted(files)) for name, files in sorted(found.items())}


def uncovered_loops() -> tuple[str, ...]:
    """Loop classes that no MockWorld scenario drives."""
    covered = set(covered_loops())
    return tuple(
        sorted(
            subject.class_name
            for subject in loop_subjects()
            if subject.class_name not in covered
        )
    )
