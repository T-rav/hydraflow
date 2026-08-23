"""The registry of path-membership collections under repo-wide enforcement.

A *path-membership collection* is a set/tuple/dict of source paths or path
patterns used as a membership test to decide something about a module —
"critical path", "self-modification", "high fanout", "elevated audit stratum".
The failure mode they all share is documented in :mod:`path_membership`: the
day a module named by a literal entry becomes a package, the entry stops
matching and the gate silently stops firing.

**If you add such a collection, register it here.** Registration is manual and
explicit on purpose: discovery-by-convention would be exactly the failure mode
one level up — a rule that quietly stops seeing its subject. The properties in
``test_path_membership_registry.py`` run over whatever this returns, and a
collection nobody registers is a collection nobody protects.

Lives under ``tests/architecture/`` alongside ``sandbox_seam_scan``,
``subprocess_reap_scan`` and ``mixin_seam_scan`` — the repo's other structural
scanners. Keeping it out of ``src/`` also keeps ``src/path_membership.py``
free of filesystem reads and ``__file__`` root-walking (#11589).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable

__all__ = [
    "EntryKind",
    "MatchKind",
    "PathMembership",
    "classify_entry",
    "package_probe_for_entry",
    "registered_path_memberships",
    "repo_paths",
    "repo_root",
]


# --------------------------------------------------------------------------
# Entry classification — what liveness means for a given entry
# --------------------------------------------------------------------------

EntryKind = Literal["module", "tree", "prefix", "fragment"]
MatchKind = Literal["exact", "glob", "substring"]

# Top-level directories a repo-anchored entry can start with. An entry whose
# first component is not one of these is a free-floating fragment (``secret``,
# ``/migration``, ``schema_evolution``) — deliberately forward-looking needles
# that are allowed to match nothing today.
_REPO_ROOTS: frozenset[str] = frozenset(
    {"src", "tests", "scripts", "docs", "repo_wiki", "dashboard", ".github"}
)


def classify_entry(entry: str) -> EntryKind:
    """Classify what kind of thing *entry* claims to name.

    - ``module``   — repo-anchored and ends in ``.py``. Must resolve as a file
      or as the package that file became, and must keep matching when its
      module is decomposed.
    - ``tree``     — repo-anchored and ends in ``/``. Must be a real directory.
    - ``prefix``   — repo-anchored, no extension. Must prefix a real path.
    - ``fragment`` — not repo-anchored. Exempt from liveness: these needles
      (``secret``, ``token``, ``_migration.py``) are written to catch files
      that do not exist yet, so "matches nothing today" is their normal state
      rather than evidence of rot.
    """
    stripped = entry.rstrip("/")
    head = stripped.split("/", 1)[0]
    if not stripped or head not in _REPO_ROOTS:
        return "fragment"
    if entry.endswith("/"):
        return "tree"
    if entry.endswith(".py"):
        return "module"
    return "prefix"


def package_probe_for_entry(entry: str, match_kind: MatchKind) -> str | None:
    """A synthetic package-member path that *entry* must still match.

    For the module entry ``src/review_phase.py`` this returns
    ``src/review_phase/_probe.py`` — the shape the entry's own module takes
    after decomposition. A gate whose predicate returns ``False`` for this
    probe is a gate that will silently stop covering its module the day
    someone splits it.

    Glob entries get their wildcards filled with a token first, so
    ``src/*_loop.py`` probes ``src/probemodule_loop/_probe.py``. Returns
    ``None`` for entries with no module identity to probe.
    """
    concrete = entry
    if match_kind == "glob":
        if "[" in entry or "?" in entry:
            # Character classes make a faithful instantiation ambiguous;
            # skip rather than probe something the author did not mean.
            return None
        concrete = entry.replace("**/", "").replace("*", "probemodule")
    if classify_entry(concrete) != "module":
        return None
    return f"{concrete.removesuffix('.py')}/_probe.py"


# --------------------------------------------------------------------------
# Repo inventory
# --------------------------------------------------------------------------


def repo_root() -> Path:
    """Repository root — three levels up from ``tests/architecture/``."""
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def repo_paths() -> tuple[str, ...]:
    """Every tracked path in the repo, as POSIX repo-relative strings.

    Uses ``git ls-files`` so untracked build output, virtualenvs and
    ``node_modules`` cannot make a dead entry look alive.
    """
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "ls-files"],  # noqa: S607 - git resolved from PATH by design
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return tuple(line for line in result.stdout.splitlines() if line)


@lru_cache(maxsize=1)
def _impacted_tests():  # noqa: ANN202 - module object
    """Import ``scripts/impacted_tests.py`` (``scripts`` is not a package).

    The module is registered in ``sys.modules`` BEFORE ``exec_module``: its
    ``@dataclass`` bodies resolve their own module namespace through
    ``sys.modules`` under ``from __future__ import annotations``.
    """
    name = "impacted_tests"
    if name in sys.modules:
        return sys.modules[name]
    path = repo_root() / "scripts" / "impacted_tests.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        msg = f"cannot load {path}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PathMembership:
    """One registered collection of module paths used as a membership test.

    ``matches`` is the *live production predicate*, not a re-implementation of
    it. That is the whole point: the repo-wide properties then exercise the
    code that actually gates merges, so a matcher that regresses to literal
    comparison is caught even when the entries themselves are untouched.
    """

    name: str
    """Dotted identifier, e.g. ``review_advisor.CRITICAL_PATHS_EXACT``."""

    entries: tuple[str, ...]
    """The collection's literal contents."""

    match_kind: MatchKind
    """How the production code compares a path against ``entries``."""

    matches: Callable[[str], bool]
    """The live predicate the production code uses for this collection."""

    why: str
    """What silently stops happening when an entry here goes dead."""

    package_blind_reason: str | None = None
    """Why this collection is exempt from the package-follows-module property.

    ``None`` — the default and the goal — means the property is enforced. A
    non-``None`` reason must explain why a decomposition failing to match here
    is acceptable, which in practice only holds when the failure is LOUD (an
    ImportError, a missing-file crash) rather than a silent ``False``. The
    count of exempt collections is itself ratcheted shrink-only.
    """


def registered_path_memberships() -> tuple[PathMembership, ...]:
    """Every path-membership collection under repo-wide enforcement."""
    import adr_drift
    import judge_independence as ji
    import prompt_refiner
    import review_advisor as ra
    import sensor_rules
    from audit import stratify
    from sensor_enricher import FileChanged

    def _class_probe(cls: ji.BlastRadiusClass) -> Callable[[str], bool]:
        return lambda path: cls in ji.classify_paths([path])

    def _stratum(name: str, markers: tuple[str, ...]) -> PathMembership:
        return PathMembership(
            name=f"audit.stratify._{name.upper()}_MARKERS",
            entries=markers,
            match_kind="substring",
            matches=lambda p: stratify._matches((p,), markers),  # noqa: SLF001
            why=(
                f"A dead marker drops changes out of the {name} stratum, "
                "silently lowering their re-audit sampling probability back "
                "to the routine base rate."
            ),
        )

    sensor_patterns: list[str] = []
    for rule in sensor_rules.SEED_RULES:
        if isinstance(rule.trigger, FileChanged):
            pattern = rule.trigger.pattern
            sensor_patterns.extend((pattern,) if isinstance(pattern, str) else pattern)

    def _sensor_fires(path: str) -> bool:
        return any(
            rule.trigger.matches(raw_output="", changed_files=[Path(path)])
            for rule in sensor_rules.SEED_RULES
            if isinstance(rule.trigger, FileChanged)
        )

    skill_modules = frozenset(prompt_refiner.SKILL_BUILDER_MODULES.values())

    return (
        PathMembership(
            name="review_advisor.CRITICAL_PATHS_EXACT",
            entries=tuple(sorted(ra.CRITICAL_PATHS_EXACT)),
            match_kind="exact",
            matches=ra.is_critical_path,
            why=(
                "A dead entry drops the module from 'critical': blast radius "
                "falls high->low, min_review_passes drops 3->1, and pre-flight "
                "stops being forced."
            ),
        ),
        PathMembership(
            name="review_advisor.CRITICAL_PATH_GLOBS",
            entries=ra.CRITICAL_PATH_GLOBS,
            match_kind="glob",
            matches=ra.is_critical_path,
            why=(
                "Same downgrade as CRITICAL_PATHS_EXACT, but a glob that "
                "matches nothing is even quieter — 'src/persistence/*' named "
                "a directory that never existed, for 107 days."
            ),
        ),
        PathMembership(
            name="review_advisor.SELF_MODIFYING_PATHS",
            entries=tuple(sorted(ra.SELF_MODIFYING_PATHS)),
            match_kind="exact",
            matches=ra.is_self_modifying_path,
            why=(
                "T29 (spec 5.8): a dead entry lets the advisor silently "
                "APPROVE changes to its own implementation on an advisory "
                "surface, instead of being forced to veto authority."
            ),
        ),
        PathMembership(
            name="judge_independence._SELF_MOD_SUBSTRINGS",
            entries=ji.SELF_MOD_PATHS,
            match_kind="substring",
            matches=_class_probe(ji.BlastRadiusClass.SELF_MODIFICATION),
            why=(
                "ADR-0045 fail-CLOSED class. A dead entry demotes a change to "
                "the factory's own gates from 'needs an independent, "
                "out-of-family verdict' to an ordinary same-family review."
            ),
        ),
        PathMembership(
            name="judge_independence._SECURITY_SUBSTRINGS",
            entries=ji.SECURITY_PATHS,
            match_kind="substring",
            matches=_class_probe(ji.BlastRadiusClass.SECURITY),
            why=(
                "A dead entry drops the security blast-radius class, so the "
                "change no longer requires an independent verdict."
            ),
        ),
        PathMembership(
            name="judge_independence._MIGRATION_SUBSTRINGS",
            entries=ji.MIGRATION_PATHS,
            match_kind="substring",
            matches=_class_probe(ji.BlastRadiusClass.MIGRATION),
            why=(
                "A dead entry drops the data-migration blast-radius class, so "
                "the change no longer requires an independent verdict."
            ),
        ),
        PathMembership(
            name="judge_independence._STRUCTURAL_SUBSTRINGS",
            entries=ji.STRUCTURAL_PATHS,
            match_kind="substring",
            matches=_class_probe(ji.BlastRadiusClass.STRUCTURAL),
            why=(
                "A dead entry drops the structural blast-radius class. "
                "'src/persistence/' sat here too, copied from the review "
                "advisor's list, naming a directory that never existed."
            ),
        ),
        _stratum("gauntlet", stratify._GAUNTLET_MARKERS),  # noqa: SLF001
        _stratum("security", stratify._SECURITY_MARKERS),  # noqa: SLF001
        _stratum("migration", stratify._MIGRATION_MARKERS),  # noqa: SLF001
        _stratum("structural", stratify._STRUCTURAL_MARKERS),  # noqa: SLF001
        PathMembership(
            name="adr_drift._SHARED_INFRA_MODULES",
            entries=tuple(sorted(adr_drift._SHARED_INFRA_MODULES)),  # noqa: SLF001
            match_kind="exact",
            matches=adr_drift._is_shared_infra,  # noqa: SLF001
            why=(
                "A dead entry stops ADR-0136's symbol-granularity nudge from "
                "firing for that module, so bare citations of it never get "
                "walked toward the enforceable path:Symbol form."
            ),
        ),
        PathMembership(
            name="sensor_rules.SEED_RULES[FileChanged].pattern",
            entries=tuple(sensor_patterns),
            match_kind="glob",
            matches=_sensor_fires,
            why=(
                "A dead pattern stops the agent hint firing for that module. "
                "Silent by construction: a hint that never appears is "
                "indistinguishable from a hint that did not apply."
            ),
        ),
        PathMembership(
            name="impacted_tests.HIGH_FANOUT_SRC",
            entries=tuple(sorted(_impacted_tests().HIGH_FANOUT_SRC)),
            match_kind="exact",
            matches=lambda p: (
                _impacted_tests()._hard_full_suite_reason(  # noqa: SLF001
                    p, PurePosixPath(p).name
                )
                is not None
            ),
            why=(
                "A dead entry means a change to a module that can regress "
                "anything stops forcing the full suite in CI, and gets "
                "name-mapped to whatever single test file shares its stem."
            ),
        ),
        PathMembership(
            name="prompt_refiner.SKILL_BUILDER_MODULES",
            entries=tuple(sorted(skill_modules)),
            match_kind="exact",
            matches=lambda p: p in skill_modules,
            why=(
                "These paths are both the load target for a refinable skill "
                "module and the write-allowlist for the LLM's synthesized "
                "patch. A dead entry breaks refinement for that skill."
            ),
            package_blind_reason=(
                "The values are import and patch targets, not gate needles. "
                "A decomposition breaks the module load in prompt_refiner "
                "with an explicit error rather than a silent False, so this "
                "collection's failure is already loud."
            ),
        ),
    )
