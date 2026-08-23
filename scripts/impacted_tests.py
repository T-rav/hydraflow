"""Impacted-test selection (CI-speedup Tier 3).

Given the repo-relative paths changed in a PR (vs a base branch), compute the
MINIMAL set of test files worth running locally — so pre-push can run just the
tests a change plausibly affects, plus a cheap always-on floor of cross-cutting
guards, instead of the whole ~15,700-test suite.

──────────────────────────────────────────────────────────────────────────────
SAFETY PRINCIPLE (read this first)
──────────────────────────────────────────────────────────────────────────────
The one unacceptable outcome is skipping a test that WOULD have caught a
regression for a file the change touched. Speed is secondary to that. So the
tool is deliberately CONSERVATIVE: whenever it cannot confidently identify what
covers a change, it does NOT guess narrow — it returns the full-suite sentinel
(``__ALL__``). "When unsure, run everything" is the invariant; a false-narrow
selection is a correctness bug, a false-wide one is only a speed cost.

──────────────────────────────────────────────────────────────────────────────
MAPPING RULES (each a pure, unit-tested function)
──────────────────────────────────────────────────────────────────────────────
(a) A changed ``tests/**`` test module (``test_*.py`` / ``regression_*.py`` /
    ``scenario_*.py``) → include it directly. A changed shared test-infra module
    under ``tests/`` (``helpers.py``, ``*_utils.py``, fixtures) is imported by
    many suites, so it is treated as a full-suite trigger, not a single file.
(b) A changed ``src/<mod>.py`` → include the tests whose names match the repo's
    ``test_<target>*.py`` convention that actually EXIST:
    ``tests/test_<mod>.py``, ``tests/test_<mod>_*.py``, ``tests/test_<mod>*.py``,
    plus any ``tests/regressions/*<mod>*.py``. (See ``tests/test_config_*.py``
    for ``src/config.py``.) A src file that maps to ZERO name-matching tests is
    a coverage blind spot — src is imported broadly by the suite, so we cannot
    prove nothing covers it — and therefore triggers the full suite (rule e's
    spirit, applied conservatively).
(c) ALWAYS include the cheap cross-cutting guards under ``tests/architecture/``
    (ratchets / drift / structural guards). They catch cross-file regressions,
    are fast, and even docs-only changes benefit (several assert doc/ADR drift).
(d) ALWAYS include a small declared SMOKE set of core high-signal tests that
    exercise the main pipeline (config, execution, ports, DI, models,
    orchestrator, persistence). See ``SMOKE_TESTS`` for the justified picks.
(e) HIGH-FANOUT FALLBACK (critical safety): if ANY changed src file is a
    high-fanout core module that most of the codebase imports, return the
    full-suite sentinel — never risk a narrow selection. The documented set is
    ``HIGH_FANOUT_SRC`` plus anything under ``src/arch/`` and any changed
    ``conftest.py`` / ``pyproject.toml`` / ``pytest.ini``.
(f) Non-Python changes with no test mapping (docs, ``.github`` non-workflow,
    assets) contribute nothing to the mapped set — but a changed
    ``.github/workflows/**``, ``Makefile``, or ``.githooks/**`` conservatively
    triggers the full suite (they can change how every test runs).

The always-on floor from (c)+(d) is added to every non-full-suite selection,
including a docs-only diff. ``scripts/*.py`` changes get the (b) name-mapping so
this tool selects its own tests when it changes, but — unlike src — an unmapped
script does not force the full suite (scripts are standalone tooling, not
imported by the suite).

──────────────────────────────────────────────────────────────────────────────
CLI
──────────────────────────────────────────────────────────────────────────────
    impacted_tests.py <path> [<path> ...]   # changed files as args
    impacted_tests.py --base origin/staging # compute via git diff <base>...HEAD
    git diff --name-only ... | impacted_tests.py --stdin
    impacted_tests.py --bounded ...         # never __ALL__ (implement gate, #11568)

Output: the selected test file paths, one per line, sorted+deduped, on stdout.
When the full suite is required, stdout is the single sentinel line ``__ALL__``
(exit 0). Callers (see ``make test-impacted``) treat that sentinel as "run the
whole suite". The human-readable reason(s) are written to stderr.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Protocol

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from path_membership import module_identities  # noqa: E402

# The stdout token that means "run the entire suite" (rule e / conservative
# fallback). Chosen so it can never collide with a real ``tests/…`` path.
FULL_SUITE_SENTINEL = "__ALL__"

# Rule (e): top-level src modules that a large fraction of the codebase imports.
# A change here can regress almost anything, so name-mapping is unsafe — run all.
HIGH_FANOUT_SRC: frozenset[str] = frozenset(
    {
        "src/config.py",  # global config model, imported nearly everywhere
        "src/models.py",  # core domain models (State, Issue, PR, …)
        "src/orchestrator.py",  # the five concurrent async loops (ADR-0001)
        # The orchestrator is assembled from mixins (#11547) — the code that
        # used to live in orchestrator.py is just as high-fanout in its new
        # module, and `orchestrator_loops` would otherwise name-map to a
        # single test file instead of the full suite.
        "src/orchestrator_bg_workers.py",
        "src/orchestrator_common.py",
        "src/orchestrator_credits.py",
        "src/orchestrator_hitl.py",
        "src/orchestrator_lifecycle.py",
        "src/orchestrator_loops.py",
        "src/orchestrator_restart.py",
        "src/orchestrator_stats.py",
        "src/orchestrator_work.py",
        "src/service_registry.py",  # dependency-injection wiring for all loops
        "src/ports.py",  # the Port boundary every runner/loop depends on
    }
)

# Rule (e): a changed file with one of these basenames (at any depth) reshapes
# how the whole suite is built/collected/fixtured → full suite.
_FULL_SUITE_BASENAMES: frozenset[str] = frozenset(
    {
        "conftest.py",  # shared fixtures, broad blast radius
        "pyproject.toml",  # deps, pytest config, tool config
        "pytest.ini",  # (not present today, guarded for the future)
        "Makefile",  # rule (f): changes how every target/test is invoked
    }
)

# Rule (d): SMOKE set — a small, hand-picked spine of the main pipeline. Each is
# a fast, high-signal unit test for a load-bearing layer, so we always run them
# as a cheap "did the core still boot" floor regardless of the diff:
#   test_config_core        — config model core (ADR-0021-adjacent)
#   test_execution          — the execution engine / main work path
#   test_ports              — the Port boundary (ADR contracts)
#   test_service_registry   — DI wiring that assembles the loops
#   test_models_core        — core domain models
#   test_orchestrator_core  — the five-loop orchestrator core (ADR-0001)
#   test_issue_store        — issue-store persistence (ADR-0021)
#   test_event_persistence  — event/state persistence round-trips
SMOKE_TESTS: tuple[str, ...] = (
    "tests/test_config_core.py",
    "tests/test_execution.py",
    "tests/test_ports.py",
    "tests/test_service_registry.py",
    "tests/test_models_core.py",
    "tests/test_orchestrator_core.py",
    "tests/test_issue_store.py",
    "tests/test_event_persistence.py",
)

# Rule (c): glob(s) for the always-on cross-cutting guard tests. Globbed at
# runtime so newly added architecture tests are picked up automatically.
#: Recursive on purpose: a non-recursive ``tests/architecture/test_*.py``
#: silently drops any future ``tests/architecture/<sub>/test_*.py`` out of
#: the always-on CI floor, and a floor that shrinks is quiet (#11673).
ARCHITECTURE_GLOBS: tuple[str, ...] = (
    "tests/architecture/test_*.py",
    "tests/architecture/**/test_*.py",
)


class FileIndex(Protocol):
    """Minimal filesystem view the pure mapping needs (injectable for tests)."""

    def exists(self, relpath: str) -> bool:
        """Return True if ``relpath`` (repo-relative) is an existing file."""
        ...

    def glob(self, pattern: str) -> list[str]:
        """Return repo-relative files matching a single-directory glob pattern.

        Only single-level ``*`` patterns are used (no ``**``); ``*`` never
        crosses a ``/`` — matching :meth:`pathlib.Path.glob` semantics.
        """
        ...


@dataclass(frozen=True)
class RealFileIndex:
    """A :class:`FileIndex` backed by a real repo checkout."""

    root: Path

    def exists(self, relpath: str) -> bool:
        return (self.root / relpath).is_file()

    def glob(self, pattern: str) -> list[str]:
        return sorted(
            p.relative_to(self.root).as_posix()
            for p in self.root.glob(pattern)
            if p.is_file()
        )


@dataclass(frozen=True)
class InMemoryFileIndex:
    """A :class:`FileIndex` over an in-memory path set — hermetic + fast tests.

    ``glob`` mirrors single-level :meth:`pathlib.Path.glob`: the directory part
    must match exactly and ``*`` in the filename part does not cross ``/``.
    """

    paths: frozenset[str]

    def exists(self, relpath: str) -> bool:
        return relpath in self.paths

    def glob(self, pattern: str) -> list[str]:
        pat_dir, _, pat_name = pattern.rpartition("/")
        out: list[str] = []
        for p in self.paths:
            p_dir, _, p_name = p.rpartition("/")
            if p_dir == pat_dir and fnmatch(p_name, pat_name):
                out.append(p)
        return sorted(out)


@dataclass(frozen=True)
class Selection:
    """Result of impacted-test selection.

    ``full_suite`` True means "run everything" — ``test_files`` is then empty.
    ``reasons`` explains, in human terms, why each decision was made.
    """

    full_suite: bool
    test_files: tuple[str, ...]
    reasons: tuple[str, ...]


def _stem(path: str) -> str:
    """Return the module stem of a ``.py`` path (basename without extension)."""
    return path.rsplit("/", 1)[-1][: -len(".py")]


def _looks_like_test_module(basename: str) -> bool:
    """True if pytest would collect ``basename`` as a test module here.

    The repo collects ``test_*.py`` and ``regression_*.py`` (pyproject
    ``python_files``); ``scenario_*.py`` are marker-gated scenario suites.
    """
    return (
        basename.startswith("test_")
        or basename.startswith("regression_")
        or basename.startswith("scenario_")
    )


def tests_for_module_stem(stem: str, fs: FileIndex) -> frozenset[str]:
    """Rule (b): existing tests whose names match ``test_<stem>*`` + regressions.

    Pure and hermetic given ``fs``. Returns only paths that actually exist.
    """
    found: set[str] = set()
    # Exact conventional name.
    exact = f"tests/test_{stem}.py"
    if fs.exists(exact):
        found.add(exact)
    # ``test_<stem>_*.py`` and its superset ``test_<stem>*.py`` (glob only picks
    # existing files, so no need to filter). Both listed for documentation of
    # the convention even though the second subsumes the first.
    found.update(fs.glob(f"tests/test_{stem}_*.py"))
    found.update(fs.glob(f"tests/test_{stem}*.py"))
    # Regressions are named by issue number, but include any that mention the
    # module — conservative, and free when it matches nothing.
    found.update(fs.glob(f"tests/regressions/*{stem}*.py"))
    return frozenset(found)


def _hard_full_suite_reason(path: str, basename: str) -> str | None:
    """Rules (e)+(f): does this path unconditionally force the full suite?

    These triggers do not depend on any test-name mapping — they reshape how the
    whole suite is built/collected or touch a module the codebase imports broadly.
    """
    if basename in _FULL_SUITE_BASENAMES:
        return f"{path}: {basename} changed -> full suite"
    if path.startswith(".github/workflows/"):
        return f"{path}: workflow changed -> full suite"
    if path.startswith(".githooks/"):
        return f"{path}: git hook changed -> full suite"
    # #11136: `.claude/hooks/**` and `.claude/settings.json` control agent
    # tool-gating, secret scanning, and pre-commit validation — behavioral
    # surfaces with no per-test mapping, same class as `.githooks/`. The
    # REST of `.claude/**` (agents/, skills/, commands/ — prose assets) is a
    # DELIBERATE non-mapping: they steer LLM behavior, not test outcomes,
    # and stay on the always-on architecture+smoke floor.
    if path.startswith(".claude/hooks/") or path == ".claude/settings.json":
        return f"{path}: Claude hook/settings changed -> full suite"
    # Membership follows the MODULE (#11669). A bare ``path in HIGH_FANOUT_SRC``
    # goes blind the day one of these is decomposed: ``src/config/_core.py``
    # would fall through to name-mapping, and if a ``tests/test__core*.py`` ever
    # existed the full-suite trigger would silently narrow to one file.
    if any(i in HIGH_FANOUT_SRC for i in module_identities(path)) or path.startswith(
        "src/arch/"
    ):
        return f"{path}: high-fanout src -> full suite"
    return None


def _classify_src_py(path: str, fs: FileIndex) -> tuple[frozenset[str], str | None]:
    """Rule (b) for a (non-high-fanout) ``src/**/*.py`` change."""
    matched = tests_for_module_stem(_stem(path), fs)
    if matched:
        return matched, None
    # src is imported broadly; an unmapped src change is a coverage blind spot.
    return frozenset(), f"{path}: no name-matching test -> full suite (safe)"


def _classify_tests_py(path: str, basename: str) -> tuple[frozenset[str], str | None]:
    """Rule (a) for a ``tests/**/*.py`` change."""
    if basename == "__init__.py":
        return frozenset(), None  # package marker, not a test
    if _looks_like_test_module(basename):
        return frozenset({path}), None
    # Shared test infra (helpers.py, *_utils.py, fixture modules) is imported by
    # many suites -> conservatively run everything.
    return frozenset(), f"{path}: shared test infra -> full suite (safe)"


def classify_path(path: str, fs: FileIndex) -> tuple[frozenset[str], str | None]:
    """Map a single changed path to (tests-to-add, full-suite-reason-or-None).

    A non-None reason means this path alone forces the full suite; the returned
    test set is then irrelevant. This is the heart of the mapping rules and is
    exercised path-by-path in the unit tests.
    """
    p = path.strip()
    if not p:
        return frozenset(), None
    basename = p.rsplit("/", 1)[-1]

    reason = _hard_full_suite_reason(p, basename)
    if reason is not None:
        return frozenset(), reason

    if p.endswith(".py"):
        if p.startswith("src/"):
            return _classify_src_py(p, fs)
        if p.startswith("tests/"):
            return _classify_tests_py(p, basename)
        # scripts/** — name-map (so this tool selects its own test) but never a
        # full-suite trigger: scripts are standalone tooling, not imported.
        if p.startswith("scripts/"):
            return tests_for_module_stem(_stem(p), fs), None

    # Everything else — non-.py src/tests (assets, cassettes), docs, README,
    # .github non-workflow, top-level data — has no test mapping (rule f).
    return frozenset(), None


def _always_on_floor(fs: FileIndex) -> frozenset[str]:
    """Rules (c)+(d): architecture guards + existing SMOKE tests."""
    floor: set[str] = set()
    for pattern in ARCHITECTURE_GLOBS:
        floor.update(fs.glob(pattern))
    floor.update(f for f in SMOKE_TESTS if fs.exists(f))
    return frozenset(floor)


def select_tests(
    changed_files: Iterable[str], fs: FileIndex, *, bounded: bool = False
) -> Selection:
    """Compute the impacted-test selection for ``changed_files`` (pure).

    Returns a full-suite :class:`Selection` if any path forces it, otherwise the
    sorted+deduped union of mapped tests plus the always-on floor (rules c+d).

    ``bounded`` (#11568) never returns the full-suite sentinel. The
    implementer's post-build gate runs OFF the host quality lock
    (``scripts/quality_host_lock.py``), so it must never expand into an
    unlocked full suite — N concurrent implementers doing that is exactly
    the host thrash the lock exists to prevent (#11219). A path that would
    force the full suite instead keeps its name-mapped tests (a high-fanout
    ``src/`` module still runs its ``test_<mod>*`` files) plus the always-on
    floor, and its reason is recorded as deferred to CI — which runs the full
    suite once per PR and is the real gate.
    """
    reasons: list[str] = []
    collected: set[str] = set()
    full = False
    for path in changed_files:
        tests, reason = classify_path(path, fs)
        if reason is not None:
            if bounded:
                reasons.append(f"{reason} (bounded: deferred to CI)")
                p = path.strip()
                if p.startswith("src/") and p.endswith(".py"):
                    collected.update(tests_for_module_stem(_stem(p), fs))
                continue
            full = True
            reasons.append(reason)
        collected.update(tests)

    if full:
        return Selection(full_suite=True, test_files=(), reasons=tuple(reasons))

    collected.update(_always_on_floor(fs))
    return Selection(
        full_suite=False,
        test_files=tuple(sorted(collected)),
        reasons=tuple(reasons),
    )


def _repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(out.stdout.strip())


def changed_files(base_ref: str, *, repo_root: Path | None = None) -> list[str]:
    """Return repo-relative paths changed vs ``base_ref`` (``base...HEAD``).

    Uses the three-dot form so only changes on HEAD's side of the merge-base
    are considered (what this branch actually did), matching CI diff semantics.
    """
    root = repo_root or _repo_root()
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


def _read_changed(args: argparse.Namespace) -> list[str]:
    if args.files:
        return list(args.files)
    if args.base:
        return changed_files(args.base)
    # Default / --stdin: read newline-separated paths from stdin.
    return [line for line in sys.stdin.read().splitlines() if line.strip()]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="impacted_tests.py",
        description="Select the minimal impacted test files for a set of "
        "changed paths. Prints selected test files one per line, or the "
        f"sentinel {FULL_SUITE_SENTINEL!r} when the full suite is required.",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Changed repo-relative paths. If omitted, use --base or stdin.",
    )
    parser.add_argument(
        "--base",
        metavar="REF",
        help="Compute changed files from `git diff --name-only <REF>...HEAD`.",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read newline-separated changed paths from stdin (the default "
        "when neither files nor --base are given).",
    )
    parser.add_argument(
        "--bounded",
        action="store_true",
        help=f"Never print {FULL_SUITE_SENTINEL!r}: a full-suite trigger keeps "
        "its name-mapped tests + the floor and defers the full run to CI "
        "(the implement-path gate's mode, #11568).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print selection reasons and a summary to stderr.",
    )
    args = parser.parse_args(argv)

    changed = _read_changed(args)
    fs = RealFileIndex(_repo_root())
    result = select_tests(changed, fs, bounded=args.bounded)

    if args.verbose:
        for reason in result.reasons:
            print(f"  reason: {reason}", file=sys.stderr)

    if result.full_suite:
        if args.verbose:
            print("mode: FULL SUITE (sentinel __ALL__)", file=sys.stderr)
        print(FULL_SUITE_SENTINEL)
        return 0

    if args.verbose:
        mode = "impacted, bounded" if args.bounded else "impacted"
        print(
            f"mode: {mode} ({len(result.test_files)} test files)",
            file=sys.stderr,
        )
    for path in result.test_files:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
