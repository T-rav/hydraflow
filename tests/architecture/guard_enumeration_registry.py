"""Every enumeration a parametrised architecture guard iterates, and how a drop is caught.

The rule is in ``docs/standards/parametrised_guards/README.md``:

    **Parametrise over the set the guard actually iterates — the literal
    sequence, by reference.** Not a representative of it. Not a predicate that
    selects from it.

    *A rationale that cannot name its enumeration in code has not yet found its
    subject.*

**If you add a module-level sequence and feed it to ``@pytest.mark.parametrize``
under ``tests/architecture/``, classify it here.** Two classifications exist and
the difference is not cosmetic:

- a **subject** is the thing being guarded — the modules held to a rule, the
  names a module may not call, the rows of an ordered rule table. Dropping a
  member silently narrows what the guard covers, so a subject carries a
  ``detects_drop`` that exercises the LIVE guard machinery and answers "would
  removing this member be caught?";
- a **corpus** is the guard's evidence — synthetic sources fed to a detector to
  prove the detector sees each shape. Dropping a member drops a test case,
  which is a coverage question rather than a "the gate stopped seeing its
  subject" question.

``detects_drop`` is the live predicate, never a re-implementation of it — the
same discipline ``path_membership_registry`` applies to ``matches``, and for
the same reason: a gate that re-implements the derivation it is checking is
checking its own copy. A subject with no detector is allowed only with a
written reason and is ratcheted shrink-only.

Registration is manual and explicit; *noticing* an unregistered enumeration is
not. ``test_guard_enumeration_gate.py`` scans ``tests/architecture/`` and
reddens on a sequence nobody classified, which is the half that stops this
registry from being "did the author remember" one level up.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Iterable

__all__ = [
    "DENY_LIST_FLOORS",
    "EnumerationKind",
    "call_witness",
    "floor_protects",
    "import_witness",
    "GuardedEnumeration",
    "SCAN_ROOT",
    "GateSequence",
    "parametrised_module_sequences",
    "proposal_keys_read_by_parser",
    "registered_enumerations",
    "repo_root",
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


SCAN_ROOT = "tests/architecture"


class EnumerationKind(StrEnum):
    SUBJECT = "subject"
    """The thing being guarded. A dropped member narrows the guard."""

    CORPUS = "corpus"
    """The guard's evidence. A dropped member drops a test case."""


@dataclass(frozen=True)
class GuardedEnumeration:
    """One classified enumeration and, for a subject, how a drop is caught."""

    name: str
    """``<module>.<ATTRIBUTE>``. Unique, and — for anything the scan can see —
    exactly the name the scan produces, so the two meet."""

    members: tuple[str, ...]
    """Resolved BY REFERENCE from the live literal. Never re-typed here: a
    hand-copied member list is the defect this registry exists to catch,
    reproduced inside the catcher."""

    kind: EnumerationKind

    why: str
    """What silently stops being guarded when a member goes uncovered."""

    detects_drop: Callable[[str], bool] | None = None
    """Given one member, does the LIVE machinery catch its removal?

    ``None`` means undetected. Legal only with :attr:`undetected_reason`, and
    the count of them is ratcheted shrink-only.
    """

    undetected_reason: str | None = None
    """Why this sequence has no drop-detector. Required when there is none."""


# ---------------------------------------------------------------------------
# Derivations and witnesses used by the rows below
# ---------------------------------------------------------------------------


def _source_of(relative: str) -> str:
    return (repo_root() / relative).read_text(encoding="utf-8")


def call_witness(subject: str, member: str, deny_list: frozenset[str]) -> bool:
    """Does the live call-name guard flag *subject* once it calls *member*?

    The witness is the REAL module the guard reads, with one call appended —
    not a synthetic stub — and the expression is the guard's own:
    ``called_names(tree) & <deny list>``. Both halves matter. Running the
    extractor alone would answer "yes" for any name at all and never consult
    the set, which is the vacuous shape this gate exists to catch; running the
    set alone would not notice that ``called_names`` records ``run`` rather
    than ``subprocess.run``, so a dotted member would sit in the list catching
    nothing.
    """
    from tests.architecture.test_director_no_authority import called_names

    injected = (
        f"{_source_of(subject)}\n\ndef _witness(obj):\n    return obj.{member}()\n"
    )
    return member in (called_names(ast.parse(injected)) & deny_list)


def import_witness(subject: str, member: str, deny_list: frozenset[str]) -> bool:
    """Does the live import guard flag *subject* once it imports *member*?"""
    from tests.architecture.test_director_no_authority import import_roots

    injected = f"{_source_of(subject)}\n\nimport {member}\n"
    return member in (import_roots(ast.parse(injected)) & deny_list)


#: Shrink-only floors for the deny-lists, which have no derivation.
#:
#: A membership list can be pinned against a derivation — ``DECISION_PATH_MODULES``
#: against the modules that declare the claim, ``ACTUATORS`` against
#: ``src/*_worker_runner.py``. A deny-list of call names cannot: it names calls
#: that must NOT appear, and most of these name nothing in this repo at all.
#: ``ConvergenceLedger`` really has ``increment_route_backs`` and
#: ``recompute_converged``; the other six ``CONVERGENCE_WRITES`` members are
#: forward-looking needles, and ``src/ports.py`` defines none of the fifteen
#: ``FORBIDDEN_MUTATIONS``. Any derivation would reproduce a strict subset —
#: which is finding F2 again, inside the gate written to catch it.
#:
#: So the floor is an independently written high-water mark, and the property
#: is CONTAINMENT rather than equality: the deny-lists may grow freely and a
#: new member needs no ceremony, but a member that has ever been denied cannot
#: quietly stop being. That is the same shape as the repo's ``GRANDFATHERED_*``
#: baselines, inverted — a floor rather than a ceiling — and it is not a second
#: copy of a vocabulary for the same reason a ratchet baseline is not: it
#: records where the guard has been, not what the guard is.
#:
#: Every live member is separately witnessed against the guard's own extractor,
#: so a floor entry cannot rot into a name nothing could ever match.
DENY_LIST_FLOORS: dict[str, frozenset[str]] = {
    "test_director_no_authority.FORBIDDEN_MUTATIONS": frozenset(
        {
            "add_label",
            "add_labels",
            "close_issue",
            "create_comment",
            "create_pr",
            "create_pull_request",
            "enable_auto_merge",
            "merge_pr",
            "merge_pull_request",
            "post_comment",
            "remove_label",
            "remove_labels",
            "set_labels",
            "squash_merge",
            "swap_pipeline_labels",
        }
    ),
    "test_director_no_authority.CONVERGENCE_WRITES": frozenset(
        {
            "add_open_concern",
            "increment_route_backs",
            "recompute_converged",
            "record_lap",
            "record_stage_transition",
            "record_sub_state_transition",
            "resolve_open_concern",
            "set_converged",
        }
    ),
    "test_director_no_authority.WRITE_PRIMITIVES": frozenset(
        {
            "commit",
            "commit_all",
            "create_commit",
            "force_push",
            "push_branch",
            "stage_all",
            "write_bytes",
            "write_text",
        }
    ),
    "test_director_no_authority._SPAWN_MACHINERY": frozenset(
        {"multiprocessing", "subprocess"}
    ),
}


def floor_protects(name: str, live: frozenset[str], member: str) -> bool:
    """Would dropping *member* from *live* break its shrink-only floor?

    The registry's ``detects_drop`` for a deny-list. It runs the real
    comparison over the real objects rather than asserting either is present:
    a member the floor does not carry is a member whose removal nothing would
    notice, and this answers ``False`` for it.
    """
    floor = DENY_LIST_FLOORS[name]
    return not floor <= (live - {member})


def proposal_keys_read_by_parser() -> frozenset[str]:
    """Every literal key ``parse_review_proposal`` actually reads off the reply.

    ``review_worker_runner`` documents ``_PROPOSAL_KEYS`` as "the written
    record of what may arrive" and as inert — it filters nothing. A written
    record attached to nothing drifts silently in both directions, which is
    what #11723 found: dropping ``"summary"`` reddened nothing, and a new
    ``raw.get("verdict")`` would have been listed nowhere.

    This derives the record from the reads, so the two cannot part company.
    """
    tree = ast.parse(_source_of("src/review_worker_runner.py"))
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.FunctionDef) and node.name == "parse_review_proposal"
        ):
            continue
        keys = set()
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            if not (isinstance(func, ast.Attribute) and func.attr == "get"):
                continue
            if not (isinstance(func.value, ast.Name) and func.value.id == "raw"):
                continue
            if call.args and isinstance(call.args[0], ast.Constant):
                first = call.args[0].value
                if isinstance(first, str):
                    keys.add(first)
        return frozenset(keys)
    return frozenset()


# ---------------------------------------------------------------------------
# The scan — which sequences an arch guard parametrises over
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateSequence:
    """One module-level sequence fed to ``@pytest.mark.parametrize``."""

    name: str
    path: str


#: Test modules the scan does not require a classification for, and why.
#: One entry, and it is the gate's own file: its parametrisations iterate this
#: registry, so classifying them here would make the registry its own subject.
#: The completeness that matters for it is asserted the other way round —
#: ``test_every_parametrised_arch_sequence_is_classified`` reddens when a row
#: is dropped and the sequence it named goes unclassified.
SCAN_EXEMPT_MODULES: frozenset[str] = frozenset({"test_guard_enumeration_gate"})


def parametrised_module_sequences() -> tuple[GateSequence, ...]:
    """Every module-level sequence an arch test feeds to ``parametrize``.

    Deliberately a scan and not a list. A list here would be the same defect
    one level up: an enumeration of enumerations that nobody notices going
    stale.
    """
    found: list[GateSequence] = []
    root = repo_root()
    for path in sorted((root / SCAN_ROOT).glob("test_*.py")):
        if path.stem in SCAN_EXEMPT_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        bound: set[str] = set()
        for node in tree.body:
            targets: Iterable[ast.expr]
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = (node.target,)
            else:
                continue
            bound.update(t.id for t in targets if isinstance(t, ast.Name))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "parametrize"):
                continue
            for arg in node.args[1:]:
                if isinstance(arg, ast.Name) and arg.id in bound:
                    found.append(
                        GateSequence(
                            f"{path.stem}.{arg.id}", str(path.relative_to(root))
                        )
                    )
    return tuple(sorted(set(found), key=lambda s: s.name))


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def registered_enumerations() -> tuple[GuardedEnumeration, ...]:
    """Every classified enumeration under the drop-detection gate."""
    import plan_broker
    import review_worker_runner as rwr
    from tests.architecture import canary_registry
    from tests.architecture import test_admission_rule_tables as admission
    from tests.architecture import test_audit_src_layout_ratchet as src_layout
    from tests.architecture import test_canary_family_conformance as canary_sweep
    from tests.architecture import test_director_no_authority as director
    from tests.architecture import test_fatal_exception_set_centralized as fatal
    from tests.architecture import test_path_membership_registry as membership
    from tests.architecture import test_ratchet_baseline_keys_resolve as baselines
    from tests.architecture import test_runtime_caches_not_tracked as caches
    from tests.architecture import test_wiki_runtime_caches_untracked as wiki_caches

    decision_path = director.claiming_modules()
    actuators = director.brokered_actuator_modules()
    canaries = {row.name for row in canary_registry.discovered_canaries()}
    proposal_keys = proposal_keys_read_by_parser()
    phase_rows = {
        reason.name
        for reason in plan_broker.PlanRouteReason
        if reason.name.startswith("PHASE_NOT_")
    }

    return (
        # --- SUBJECTS, derived ------------------------------------------
        GuardedEnumeration(
            name="test_director_no_authority.DECISION_PATH_MODULES",
            members=tuple(director.DECISION_PATH_MODULES),
            kind=EnumerationKind.SUBJECT,
            detects_drop=lambda member: member in decision_path,
            why=(
                "#11723 F2. Every guard in that file iterates this tuple; a "
                "dropped entry stops being checked for spawn, label mutation, "
                "convergence writes and raw-import machinery at once, and the "
                "predicate that was supposed to catch it matched 4 of 10."
            ),
        ),
        GuardedEnumeration(
            name="test_director_no_authority.ACTUATORS",
            members=tuple(module for module, _seam in director.ACTUATORS),
            kind=EnumerationKind.SUBJECT,
            detects_drop=lambda member: member in actuators,
            why=(
                "Dropping the review row silently un-guarded THREE parametrised "
                "checks against the module that spawns the reviewer — including "
                "the sandbox seam declaration that stops an air-gapped scenario "
                "spawning a real worker."
            ),
        ),
        GuardedEnumeration(
            name="review_worker_runner._PROPOSAL_KEYS",
            members=tuple(sorted(rwr._PROPOSAL_KEYS)),  # noqa: SLF001
            kind=EnumerationKind.SUBJECT,
            detects_drop=lambda member: member in proposal_keys,
            why=(
                "The written record of what may arrive on an untrusted reply. "
                "It filters nothing, so it drifts in silence both ways: a "
                "dropped key mis-documents the boundary, and a key read by a "
                "new .get() is recorded nowhere."
            ),
        ),
        GuardedEnumeration(
            name="test_canary_family_conformance.CANARIES",
            members=tuple(row.name for row in canary_sweep.CANARIES),
            kind=EnumerationKind.SUBJECT,
            detects_drop=lambda member: member in canaries,
            why=(
                "#11716. One rule stated in six places; the off-switch went "
                "unpinned in 5 of 6 and clause 2's canonicalisation in 6 of 6. "
                "A canary dropped from this registry inherits neither pin, and "
                "a fourth canary that never joins it inherits nothing at all."
            ),
        ),
        GuardedEnumeration(
            name="test_canary_family_conformance._PHASE_ROWS",
            members=tuple(reason.name for reason in canary_sweep._PHASE_ROWS),  # noqa: SLF001
            kind=EnumerationKind.SUBJECT,
            detects_drop=lambda member: member in phase_rows,
            why=(
                "#11716 residue 1. ROLE_PHASE_FORBIDDEN claims the CATALOGUE "
                "forbids the role; a phase outside the canary's bound says "
                "nothing about the role. A dropped row stops the distinction "
                "being checked for that phase, and flipping it survives."
            ),
        ),
        # --- SUBJECTS, floored ------------------------------------------
        GuardedEnumeration(
            name="test_director_no_authority.FORBIDDEN_MUTATIONS",
            members=tuple(sorted(director.FORBIDDEN_MUTATIONS)),
            kind=EnumerationKind.SUBJECT,
            detects_drop=lambda member: floor_protects(
                "test_director_no_authority.FORBIDDEN_MUTATIONS",
                director.FORBIDDEN_MUTATIONS,
                member,
            ),
            why=(
                "Dropping 'merge_pr' survives, silently un-guarding the 'no "
                "merge action' half of #11537's second acceptance criterion "
                "across every decision-path module and every actuator."
            ),
        ),
        GuardedEnumeration(
            name="test_director_no_authority.CONVERGENCE_WRITES",
            members=tuple(sorted(director.CONVERGENCE_WRITES)),
            kind=EnumerationKind.SUBJECT,
            detects_drop=lambda member: floor_protects(
                "test_director_no_authority.CONVERGENCE_WRITES",
                director.CONVERGENCE_WRITES,
                member,
            ),
            why=(
                "ADR-0137's narrowing of ADR-0094: the ConvergenceLedger stays "
                "the sole owner of convergence state. A dropped call name lets "
                "an actuator keep a second copy of the lap."
            ),
        ),
        GuardedEnumeration(
            name="test_director_no_authority.WRITE_PRIMITIVES",
            members=tuple(sorted(director.WRITE_PRIMITIVES)),
            kind=EnumerationKind.SUBJECT,
            detects_drop=lambda member: floor_protects(
                "test_director_no_authority.WRITE_PRIMITIVES",
                director.WRITE_PRIMITIVES,
                member,
            ),
            why=(
                "#11542's sixth acceptance criterion as a property of what the "
                "module cannot reach. A dropped name is how 'let the reviewer "
                "apply its own fix' becomes a one-line change nothing reddens."
            ),
        ),
        GuardedEnumeration(
            name="test_director_no_authority._SPAWN_MACHINERY",
            members=tuple(sorted(director._SPAWN_MACHINERY)),  # noqa: SLF001
            kind=EnumerationKind.SUBJECT,
            detects_drop=lambda member: floor_protects(
                "test_director_no_authority._SPAWN_MACHINERY",
                director._SPAWN_MACHINERY,  # noqa: SLF001
                member,
            ),
            why=(
                "The constant introduced BY the fix for this class, with no "
                "drops guard of its own. Dropping 'multiprocessing' leaves a "
                "raw spawn on the decision path invisible to the call-site "
                "guards, which know only sanctioned helper names."
            ),
        ),
        GuardedEnumeration(
            name="test_admission_rule_tables.FENCING_WITNESSES",
            members=tuple(
                witness.reason.value for witness in admission.FENCING_WITNESSES
            ),
            kind=EnumerationKind.SUBJECT,
            detects_drop=admission.fencing_row_is_reachable,
            why=(
                "The first-match fence table. A dropped row makes its reason "
                "unreachable and the request falls through to a weaker one — "
                "a stop fence reported as a capacity problem."
            ),
        ),
        GuardedEnumeration(
            name="test_admission_rule_tables.LEGALITY_WITNESSES",
            members=tuple(
                witness.reason.value for witness in admission.LEGALITY_WITNESSES
            ),
            kind=EnumerationKind.SUBJECT,
            detects_drop=admission.legality_row_is_reachable,
            why=(
                "#11723 F1. Nine of ten adjacent swaps survived the suite, and "
                "one downgraded a held-foreign-lease theft event out of "
                "ADR-0137 B5's counter. Order IS the contract here."
            ),
        ),
        # --- SUBJECTS with no detector yet (ratcheted shrink-only) -------
        GuardedEnumeration(
            name="test_path_membership_registry.MEMBERSHIPS",
            members=tuple(m.name for m in membership.MEMBERSHIPS),
            kind=EnumerationKind.SUBJECT,
            why=(
                "A dropped row stops a merge-gating path collection being "
                "checked for dead entries and for package-blindness — the "
                "#11669 class, which ran inert for 104 days."
            ),
            undetected_reason=(
                "A registry of registries. The detector would have to derive "
                "every path-membership collection in the repo, which is that "
                "registry's own documented open problem ('registration is "
                "manual and explicit on purpose') rather than this gate's."
            ),
        ),
        GuardedEnumeration(
            name="test_ratchet_baseline_keys_resolve._CODE_BASELINES",
            members=tuple(name for name, _path, _symbol in baselines._CODE_BASELINES),  # noqa: SLF001
            kind=EnumerationKind.SUBJECT,
            why=(
                "A dropped row stops checking that a grandfather baseline's "
                "keys still resolve, so the baseline silently exempts nothing "
                "and the ratchet it belongs to stops ratcheting."
            ),
            undetected_reason=(
                "The derivation is 'every grandfather baseline in the repo', "
                "which needs a naming convention the baselines do not yet "
                "share. Tractable, and not this issue's subject."
            ),
        ),
        GuardedEnumeration(
            name="test_runtime_caches_not_tracked.WIKI_9537_CACHES",
            members=tuple(caches.WIKI_9537_CACHES),
            kind=EnumerationKind.SUBJECT,
            why=(
                "A dropped path lets a runtime cache be committed, which is "
                "the #9537 shape: a loop's own scratch file tracked in git and "
                "rewritten on every tick."
            ),
            undetected_reason=(
                "The derivation is 'every path RepoWikiLoop writes at runtime', "
                "which is not stated anywhere in code today. The duplicate list "
                "in test_wiki_runtime_caches_untracked is the same gap."
            ),
        ),
        GuardedEnumeration(
            name="test_wiki_runtime_caches_untracked.RUNTIME_CACHES",
            members=tuple(wiki_caches.RUNTIME_CACHES),
            kind=EnumerationKind.SUBJECT,
            why="The same three paths as WIKI_9537_CACHES, in a second file.",
            undetected_reason=(
                "Same gap as WIKI_9537_CACHES, and the two lists being "
                "hand-copies of each other is the finding underneath both."
            ),
        ),
        # --- CORPORA ----------------------------------------------------
        GuardedEnumeration(
            name="test_audit_src_layout_ratchet._FORBIDDEN_SHAPES",
            members=tuple(param.id or "" for param in src_layout._FORBIDDEN_SHAPES),  # noqa: SLF001
            kind=EnumerationKind.CORPUS,
            why="Synthetic sources the layout detector must flag.",
            undetected_reason=(
                "Evidence, not subject: each member is a source shape fed to "
                "the detector. Dropping one narrows the proof that the "
                "detector sees that spelling — a coverage question, answered "
                "by the ratchet these feed rather than by a drop-detector."
            ),
        ),
        GuardedEnumeration(
            name="test_audit_src_layout_ratchet._ALLOWED_SHAPES",
            members=tuple(param.id or "" for param in src_layout._ALLOWED_SHAPES),  # noqa: SLF001
            kind=EnumerationKind.CORPUS,
            why="Synthetic sources the layout detector must NOT flag.",
            undetected_reason=(
                "Evidence, not subject — the false-positive half of the same corpus."
            ),
        ),
        GuardedEnumeration(
            name="test_fatal_exception_set_centralized._RESTATEMENT_SHAPES",
            members=tuple(param.id or "" for param in fatal._RESTATEMENT_SHAPES),  # noqa: SLF001
            kind=EnumerationKind.CORPUS,
            why="Synthetic sources the fatal-set restatement detector must flag.",
            undetected_reason="Evidence, not subject: source shapes fed to a detector.",
        ),
        GuardedEnumeration(
            name="test_fatal_exception_set_centralized._INNOCENT_SHAPES",
            members=tuple(param.id or "" for param in fatal._INNOCENT_SHAPES),  # noqa: SLF001
            kind=EnumerationKind.CORPUS,
            why="Synthetic sources the same detector must NOT flag.",
            undetected_reason="Evidence, not subject — the false-positive half.",
        ),
    )
