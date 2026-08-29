"""The import boundaries this repo enforces, stated as data.

Three guards used to state these rules as three hand-rolled AST walks, and each
walk was narrower than the vocabulary of the thing it guarded — see
:mod:`tests.architecture.import_edge_scan` for the three mutation-proven bugs.
The walks are gone. What is left is: one collector, one driver
(``test_import_boundary_gate.py``), and the declarations below.

**Five properties every declaration carries, each earned by a real finding in
this repo.** They are not optional and they are not checked by review:

1. **:attr:`ImportBoundary.min_subjects`, enforced by the DRIVER.** A gate
   whose corpus comes back empty reports serenity. The driver checks the
   subject count for every declaration before believing any verdict, so the
   check is free and cannot be forgotten for the next boundary.
2. **Every path, pattern and glob resolves AT LOAD TIME.** :func:`declarations`
   raises :class:`ImportBoundaryError` on a root that matches nothing or an
   exclusion that names nothing. A missing subject is a hard error, never a
   skip: four ``make audit`` checks sat inert for years because a deleted file
   produced ``NA``.
3. **:attr:`ImportBoundary.witnesses` is mandatory, in both directions.** The
   declaration states how it fails, and the driver runs those statements
   through the LIVE collector — never a re-implementation of it, the same
   discipline ``guard_enumeration_registry`` applies to ``detects_drop`` and
   ``path_membership_registry`` applies to ``matches``. This is the property
   that would have caught all three bugs at authoring time: the author of the
   OTel ban would have had to write ``from telemetry import spans`` as a
   must-flag witness and would have found the predicate could not express it.
4. **Every exclusion carries a written reason**, not a bare path.
5. **No behaviour lost.** Every spelling the three replaced guards caught is
   still caught, and each one is pinned as a witness below rather than
   asserted in a PR description.

Adding a boundary means adding a row here and its name to
``guard_enumeration_registry.IMPORT_BOUNDARY_FLOOR``. Two objects that must
agree is the only arrangement in which losing one reddens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

__all__ = [
    "Denied",
    "Exclusion",
    "ImportBoundary",
    "ImportBoundaryError",
    "Scope",
    "Witness",
    "declarations",
    "repo_root",
    "sys_path_roots",
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def sys_path_roots() -> tuple[Path, ...]:
    """The roots a dotted module name resolves against, in ``sys.path`` order.

    Mirrors what ``tests/conftest.py`` puts on the path: ``src/`` then the repo
    root. Used to resolve relative imports to absolute names and to answer the
    submodule-vs-symbol question in a failure message.
    """
    root = repo_root()
    return (root / "src", root)


#: Path components a subject glob never means, and why. A directory of build
#: output is not a subject; a guard that scans one is measuring its own cache.
_IGNORED_PARTS: Final[frozenset[str]] = frozenset(
    {".venv", "__pycache__", "node_modules", "hydraflow.egg-info", ".mypy_cache"}
)


class ImportBoundaryError(RuntimeError):
    """A declaration that does not resolve. Raised at load time, never skipped."""


class Scope(StrEnum):
    """Which edges a boundary's verdict reads."""

    BOOT = "boot"
    """Only edges reachable when the module is imported.

    For a rule whose subject is a RUNTIME property of importing the module —
    the container ships ``src`` and not ``scripts``, so a boot-time reach exits
    the process. A lazy import inside a function is not that failure and is
    deliberately permitted.
    """

    ANY = "any"
    """Every edge, lazy ones included.

    For a rule about whether the dependency may exist at all. A lazily imported
    OTel client is still an OTel dependency.
    """


@dataclass(frozen=True, slots=True)
class Denied:
    """One denied module, and why it is denied.

    Matching is dotted-prefix on whole components, so ``telemetry.spans`` also
    denies ``telemetry.spans.anything`` and does not deny ``telemetry_spans``.
    """

    module: str
    reason: str


@dataclass(frozen=True, slots=True)
class Exclusion:
    """One path a boundary does not apply to, and why.

    A bare path in an exclusion list is indistinguishable from an oversight a
    year later, so the reason is a field rather than a comment.
    """

    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class Witness:
    """A synthetic module, and the verdict the LIVE machinery must reach on it.

    ``flagged=True`` says this spelling MUST be caught; ``flagged=False`` says
    it must not. Both directions are mandatory: a boundary with only positives
    cannot tell a working predicate from ``return True``, and a boundary with
    only negatives cannot tell one from ``return False``.
    """

    name: str
    source: str
    flagged: bool
    why: str


@dataclass(frozen=True, slots=True)
class ImportBoundary:
    """One import rule, stated as data and run by the generic driver."""

    name: str
    """Stable id. Also the key in ``IMPORT_BOUNDARY_FLOOR``."""

    rule: str
    """The rule in one sentence, as it would be said to a person."""

    roots: tuple[str, ...]
    """Repo-relative globs naming the subjects. Resolved at load time; a glob
    that matches nothing is a hard error, not an empty scan."""

    denied: tuple[Denied, ...]
    scope: Scope

    min_subjects: int
    """Floor on the resolved subject count, enforced by the driver.

    An anti-vacuity floor, not a ratchet: it answers "did the corpus collapse",
    so it sits well below the live count for a glob-resolved subject and
    exactly at it for an enumerated one. Raising it is not how a growing tree
    is tracked.
    """

    witnesses: tuple[Witness, ...]
    failure: str
    """What the reader should do about a violation."""

    exclusions: tuple[Exclusion, ...] = field(default_factory=tuple)

    def denied_modules(self) -> tuple[str, ...]:
        return tuple(entry.module for entry in self.denied)

    def subjects(self) -> tuple[Path, ...]:
        """The files this boundary applies to, resolved against the repo."""
        root = repo_root()
        found: list[Path] = []
        for pattern in self.roots:
            matched = sorted(
                path
                for path in root.glob(pattern)
                if path.is_file()
                and path.suffix == ".py"
                and not _IGNORED_PARTS.intersection(path.parts)
            )
            if not matched:
                msg = (
                    f"{self.name}: root pattern {pattern!r} matches no Python file "
                    "under the repo. A subject that has stopped resolving is the "
                    "defect this gate exists to catch, so it is a load error "
                    "rather than an empty scan."
                )
                raise ImportBoundaryError(msg)
            found.extend(matched)
        excluded = self._excluded_paths(root)
        return tuple(
            path
            for path in dict.fromkeys(found)
            if not any(path == other or other in path.parents for other in excluded)
        )

    def _excluded_paths(self, root: Path) -> tuple[Path, ...]:
        resolved: list[Path] = []
        for exclusion in self.exclusions:
            path = root / exclusion.path
            if not path.exists():
                msg = (
                    f"{self.name}: exclusion {exclusion.path!r} names nothing on "
                    "disk. An exclusion for a path that no longer exists exempts "
                    "nothing and reads as caution — delete it."
                )
                raise ImportBoundaryError(msg)
            resolved.append(path)
        return tuple(resolved)


def _validated(boundaries: Sequence[ImportBoundary]) -> tuple[ImportBoundary, ...]:
    """Resolve every declaration NOW, so a broken one cannot load and skip.

    Property 2. The alternative — resolving lazily inside each test — is how a
    guard whose subject was deleted goes green: the scan finds nothing, the
    assertion over nothing holds, and the dashboard says enforced.
    """
    seen: set[str] = set()
    for boundary in boundaries:
        if boundary.name in seen:
            msg = f"duplicate import-boundary name {boundary.name!r}"
            raise ImportBoundaryError(msg)
        seen.add(boundary.name)
        if not boundary.denied:
            msg = f"{boundary.name}: denies nothing, so it cannot ever fire"
            raise ImportBoundaryError(msg)
        boundary.subjects()
    return tuple(boundaries)


# ---------------------------------------------------------------------------
# The declarations
# ---------------------------------------------------------------------------

#: Subjects under ``src/`` number 764 files today. The floor answers "has the
#: corpus collapsed", so it sits an order of magnitude below that: a glob that
#: has stopped resolving returns 0 or a handful, never 200.
_SRC_SUBJECT_FLOOR: Final = 200


def _no_otel_under_src() -> ImportBoundary:
    """ADR-0118: production code carries no OpenTelemetry dependency."""
    return ImportBoundary(
        name="no-otel-under-src",
        rule=(
            "src/ carries no OpenTelemetry dependency and no re-introduced "
            "telemetry.* module (ADR-0118)."
        ),
        roots=("src/**/*.py",),
        denied=(
            Denied(
                "opentelemetry",
                "the SDK itself. ADR-0118 supersedes ADR-0055 and removes the "
                "OTel/Honeycomb layer: observability is the SRE agent's job, "
                "not instrumentation woven through every loop and port.",
            ),
            Denied(
                "telemetry.spans",
                "the span decorators (@runner_span/@loop_span/@port_span) that "
                "wove OTel into the hot path. Re-introducing the module is how "
                "the layer comes back without anyone deciding to.",
            ),
            Denied(
                "telemetry.otel",
                "the tracer/exporter bootstrap. Its return is the whole of "
                "ADR-0055 returning.",
            ),
            Denied(
                "telemetry.subprocess_bridge",
                "trace-context propagation into spawned workers — the piece "
                "that made the instrumentation reach past the process boundary.",
            ),
            Denied(
                "telemetry.slugs",
                "the span-name vocabulary. Harmless alone, and exactly the "
                "first file back if the layer is rebuilt.",
            ),
        ),
        # ANY, not BOOT: ADR-0118 removed the dependency, not merely its
        # boot cost. A lazily imported tracer is still the layer.
        scope=Scope.ANY,
        min_subjects=_SRC_SUBJECT_FLOOR,
        witnesses=(
            Witness(
                name="from-package-import-submodule",
                source="from telemetry import spans\n",
                flagged=True,
                why=(
                    "THE bug this collector was written for. The guard this "
                    "replaces tested ImportFrom.module against a dotted "
                    "deny-list and never alias.name, so the only spelling "
                    "anyone writes passed while `import telemetry.spans` "
                    "failed. ADR-0118's ban caught the spelling nobody uses."
                ),
            ),
            Witness(
                name="dotted-import",
                source="import telemetry.spans\n",
                flagged=True,
                why="The spelling the old guard did catch. Still caught.",
            ),
            Witness(
                name="sdk-submodule",
                source="from opentelemetry import trace\n",
                flagged=True,
                why="Prefix denial reaches the whole SDK, not just its root.",
            ),
            Witness(
                name="lazy-import-still-a-dependency",
                source="def _t():\n    import opentelemetry.trace\n    return 1\n",
                flagged=True,
                why=(
                    "Scope.ANY. Deferring the import defers the cost, not the "
                    "dependency, and ADR-0118 removed the dependency."
                ),
            ),
            Witness(
                name="prefix-is-not-substring",
                source="import telemetry_utils\nfrom telemetryx import spans\n",
                flagged=False,
                why=(
                    "Dotted-prefix matching is on whole components. A bare "
                    "startswith would flag both of these, and a guard that "
                    "cries wolf on unrelated names is a guard someone deletes."
                ),
            ),
            Witness(
                name="undenied-module",
                source="import a_module_no_boundary_denies\n",
                flagged=False,
                why=(
                    "The deny-list operand is load-bearing. Drop the "
                    "intersection and the collector answers True for any "
                    "import, which is how a witness proves the extractor and "
                    "nothing else."
                ),
            ),
        ),
        failure=(
            "OTel/Honeycomb was removed per ADR-0118 — observability belongs to "
            "the SRE agent (targeting New Relic), not to instrumentation woven "
            "through the loops. If you need a signal, give it to the SRE agent; "
            "reversing ADR-0118 needs a superseding ADR, not an import."
        ),
    )


def _no_scripts_at_boot_under_src() -> ImportBoundary:
    """#10365: importing a src module must not require scripts/ to exist."""
    return ImportBoundary(
        name="no-scripts-at-boot-under-src",
        rule=(
            "No src/ module reaches scripts/ at module-import time — the "
            "factory container ships src/ and not scripts/ (#10365)."
        ),
        roots=("src/**/*.py",),
        denied=(
            Denied(
                "scripts",
                "Dockerfile.agent copies src, tests, templates and static, and "
                "runs PYTHONPATH=/opt/hydraflow/src:/opt/hydraflow. scripts/ is "
                "ABSENT from the image, so a src module that reaches it at "
                "import time raises ModuleNotFoundError the instant it is "
                "imported and the container exits 1. That is exactly how "
                "#10365 broke staging: src/close_verification.py did `from "
                "scripts.hydraflow_audit.false_close import ...` at module "
                "scope, so importing post_merge_handler killed the container. "
                "The unit and audit suites missed it because they run with the "
                "repo ROOT on sys.path, where scripts IS importable.",
            ),
        ),
        # BOOT, and the narrowness is the rule rather than an approximation of
        # it. A function-local import runs when the function is called, and
        # src/gate_activation_check.py legitimately imports scripts.gates that
        # way (ADR-0082's gate-activation bridge). `if TYPE_CHECKING:` is
        # elided at runtime. Neither can break a container boot.
        scope=Scope.BOOT,
        min_subjects=_SRC_SUBJECT_FLOOR,
        witnesses=(
            Witness(
                name="dynamic-import-at-module-scope",
                source=(
                    "import importlib\n\n"
                    'CHECK = importlib.import_module("scripts.hydraflow_audit.checks.p1_docs")\n'
                ),
                flagged=True,
                why=(
                    "THE bug. This reproduces #10365 byte-for-byte — the "
                    "container raises ModuleNotFoundError on the same line — "
                    "and the guard this replaces passed it, because it read "
                    "import STATEMENTS and this is a call. "
                    "importlib.util.spec_from_file_location is already an "
                    "established idiom in three src modules, so the shape was "
                    "sitting in the tree, not hypothetical."
                ),
            ),
            Witness(
                name="spec-from-file-location-by-path",
                source=(
                    "import importlib.util\n\n"
                    'SPEC = importlib.util.spec_from_file_location("p1", "scripts/hydraflow_audit/checks/p1_docs.py")\n'
                ),
                flagged=True,
                why=(
                    "The other half of the same idiom: the module the loader "
                    "reaches is named by the PATH argument, and the first "
                    "argument is only the name it registers under."
                ),
            ),
            Witness(
                name="from-import-at-module-scope",
                source="from scripts.hydraflow_audit.checks import p1_docs\n",
                flagged=True,
                why="The spelling the old guard did catch. Still caught.",
            ),
            Witness(
                name="import-inside-a-match-arm",
                source=(
                    "import sys\n\n"
                    "match sys.platform:\n"
                    '    case "linux":\n'
                    "        import scripts.gates\n"
                    "    case _:\n"
                    "        pass\n"
                ),
                flagged=True,
                why=(
                    "The documented gap in the walk this replaces. That walk "
                    "enumerated the blocks it descended — If, For, While, "
                    "With, Try, ClassDef — and ast.Match arrived in the "
                    "language after it was written. A match arm executes at "
                    "import like any other statement. The collector states "
                    "what DEFERS execution instead, so this needed no rule."
                ),
            ),
            Witness(
                name="conditional-import-is-still-boot",
                source=(
                    "import sys\n\n"
                    "if sys.version_info >= (3, 13):\n"
                    "    from scripts import gates\n"
                ),
                flagged=True,
                why=(
                    "A branch that may run at import is a boot reach. The "
                    "static answer is deliberately the loud one."
                ),
            ),
            Witness(
                name="function-local-import",
                source=(
                    "def activate() -> int:\n"
                    "    from scripts import gates\n\n"
                    "    return gates.count()\n"
                ),
                flagged=False,
                why=(
                    "Runs when called, not when imported, so it cannot break a "
                    "container boot. src/gate_activation_check.py does exactly "
                    "this on purpose (ADR-0082). Flagging it would make the "
                    "guard wrong about the property it exists to protect."
                ),
            ),
            Witness(
                name="type-checking-only",
                source=(
                    "from typing import TYPE_CHECKING\n\n"
                    "if TYPE_CHECKING:\n"
                    "    from scripts.gates import Gate\n"
                ),
                flagged=False,
                why="Elided at runtime; the interpreter never executes it.",
            ),
            Witness(
                name="mapping-read-is-not-an-import",
                source=('import json\n\nDATA = json.loads("{}").get("scripts", {})\n'),
                flagged=False,
                why=(
                    "The measured false positive the argument-side dynamic "
                    "rule invites: package.json's `scripts` key, read at "
                    "module scope through the mapping protocol. Three src "
                    "modules do this. `get` is excluded on the collector's "
                    "SAFE side, where a miss is a loud false positive rather "
                    "than a silent hole."
                ),
            ),
            Witness(
                name="undenied-module",
                source="import scripts_helper\nfrom my.scripts import thing\n",
                flagged=False,
                why=(
                    "Whole-component prefix matching, both ends: `scripts` "
                    "does not deny `scripts_helper`, and a `scripts` package "
                    "nested under something else is a different module."
                ),
            ),
        ),
        failure=(
            "Move the shared code into src/ (as #10365 did with false_close), "
            "or defer the import into a function body or a TYPE_CHECKING block "
            "if it is genuinely not needed at boot. src/ ships in the image; "
            "scripts/ does not."
        ),
    )


def _no_spawn_machinery_on_the_decision_path(
    modules: Sequence[str],
) -> ImportBoundary:
    """ADR-0137: the modules that claim they cannot spawn must not be able to."""
    return ImportBoundary(
        name="no-spawn-machinery-on-the-decision-path",
        rule=(
            "No module on the director's decision path imports process-spawn "
            "machinery — it says in its own docstring that it does not spawn "
            "(ADR-0137, #11543)."
        ),
        roots=tuple(modules),
        denied=(
            Denied(
                "subprocess",
                "the stdlib spawn surface. SPAWN_PRIMITIVES names only "
                "HydraFlow's sanctioned helpers and the repo-wide raw-spawn "
                "ratchet knows create_subprocess_exec/Popen/spawnv, so a plain "
                "subprocess.run() in a decision-path module passed BOTH "
                "(#11543). Reaching subprocess at all requires importing it, "
                "which makes the import the cheapest true signal.",
            ),
            Denied(
                "multiprocessing",
                "the same reach through a second stdlib door. For ten modules "
                "that each claim purity, importing it at all is a rule with no "
                "false positives.",
            ),
            Denied(
                "concurrent.futures",
                "ProcessPoolExecutor reaches the exact machinery "
                "`multiprocessing` names, through a package the old pin could "
                "not express: it intersected the deny-list with the TOP-LEVEL "
                "root of each import, so `concurrent.futures` collapsed to "
                "`concurrent` and `from concurrent.futures import "
                "ProcessPoolExecutor` in src/plan_broker.py passed. The whole "
                "package is denied rather than the one class, because a "
                "module that needs a worker pool belongs behind a declared "
                "seam either way, and no decision-path module imports it "
                "today.",
            ),
        ),
        scope=Scope.ANY,
        # Exactly the live length of DECISION_PATH_MODULES. An enumerated
        # subject can be pinned rather than floored: the list gaining a module
        # is fine, the list losing one is what this catches -- and the same
        # drop reddens a second time in guard_enumeration_registry, which pins
        # the tuple against the modules that DECLARE the claim.
        min_subjects=len(modules),
        witnesses=(
            Witness(
                name="process-pool-through-concurrent-futures",
                source="from concurrent.futures import ProcessPoolExecutor\n",
                flagged=True,
                why=(
                    "THE bug. Verified against src/plan_broker.py: injecting "
                    "this line left the whole suite green, because "
                    "`concurrent.futures` was collapsed to `concurrent` before "
                    "the deny-list was consulted. Edges now carry the full "
                    "dotted path."
                ),
            ),
            Witness(
                name="stdlib-spawn-root",
                source="import multiprocessing\n",
                flagged=True,
                why="The spelling the old pin did catch. Still caught.",
            ),
            Witness(
                name="subprocess-submodule",
                source="from subprocess import run\n",
                flagged=True,
                why="Prefix denial reaches a name imported out of the package.",
            ),
            Witness(
                name="relative-reexport",
                source="from . import subprocess\n",
                flagged=False,
                why=(
                    "A relative import resolves against the importing file's "
                    "package, so inside src/ this names `subprocess` under a "
                    "local package, not the stdlib module. Resolving level>0 "
                    "is what keeps this from being a false positive -- and "
                    "what keeps a real relative reach from being invisible."
                ),
            ),
            Witness(
                name="futures-root-is-not-the-package",
                source="import concurrent\n",
                flagged=False,
                why=(
                    "`concurrent` alone reaches no executor: the submodule is "
                    "not imported, so the attribute does not exist. Denying "
                    "the root instead would have been the mirror-image error "
                    "of the bug being fixed."
                ),
            ),
            Witness(
                name="undenied-module",
                source="import a_module_no_boundary_denies\n",
                flagged=False,
                why="The deny-list operand is load-bearing.",
            ),
        ),
        failure=(
            "Every module on the decision path says in its own docstring that "
            "it does not spawn. A module that needs to spawn belongs behind a "
            "declared seam — an actuator with a seam declaration and its own "
            "row in ACTUATORS — not on this list."
        ),
    )


@lru_cache(maxsize=1)
def declarations() -> tuple[ImportBoundary, ...]:
    """Every import boundary under enforcement, resolved and validated.

    Cached: validation walks two ``src/**/*.py`` globs, and the callers below
    — the driver, the registry, and the decision path's own raw-spawn corpus —
    ask for it repeatedly. The declarations are frozen and the resolution is a
    pure function of the tree, so one answer per process is the right number.

    The decision-path subjects are read BY REFERENCE from
    ``DECISION_PATH_MODULES`` rather than copied: that tuple is already pinned
    against the modules which declare the claim, and a second copy here would
    be the defect ``docs/standards/parametrised_guards`` exists to stop. The
    import is deferred into the function body because the module that owns the
    tuple reads this one back for its raw-spawn corpus.
    """
    from tests.architecture.test_director_no_authority import DECISION_PATH_MODULES

    return _validated(
        (
            _no_otel_under_src(),
            _no_scripts_at_boot_under_src(),
            _no_spawn_machinery_on_the_decision_path(DECISION_PATH_MODULES),
        )
    )
