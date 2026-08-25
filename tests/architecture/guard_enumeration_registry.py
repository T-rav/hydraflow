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
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Iterable, Mapping

__all__ = [
    "ALLOW_LIST_NAMES",
    "DENY_LIST_FLOORS",
    "EnumerationKind",
    "call_witness",
    "declared_deny_lists",
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

    **It must resolve a different object from :attr:`members`.** Two sets
    derived from one source agree by construction, so their equality is not a
    question — the tautology that got past self-review twice while this gate
    was being written, once in ``registered_canaries()`` and once here. A
    detector that has regressed further, to ``return True``, is caught
    mechanically by ``test_a_detector_rejects_a_member_that_was_never_there``;
    one reading its own subject is caught only by reading it.

    ``None`` means undetected. Legal only with :attr:`undetected_reason`, and
    the count of them is ratcheted shrink-only.
    """

    undetected_reason: str | None = None
    """Why this sequence has no drop-detector. Required when there is none."""

    undetected_members: Mapping[str, str] = field(default_factory=dict)
    """Members whose drop is caught by a DIFFERENT mechanism, and which one.

    Kept as an exemption rather than dropped from :attr:`members`, because a
    member removed from the parametrisation is a member nobody looks at again
    — the shrinking-set trap this gate is about. Each entry names the
    mechanism that does protect it, and the total is ratcheted shrink-only.
    """


# ---------------------------------------------------------------------------
# Derivations and witnesses used by the rows below
# ---------------------------------------------------------------------------


def _source_of(relative: str) -> str:
    return (repo_root() / relative).read_text(encoding="utf-8")


def call_witness(subject: str, member: str, deny_list: frozenset[str]) -> bool:
    """Does the live call-name guard flag *subject* once it calls *member*?

    Deliberately narrow, and the narrowness is the point. Read with
    ``test_the_deny_list_operand_is_load_bearing``, which passes a name the
    list does NOT carry: together they say the extractor sees this spelling
    AND the intersection with the deny-list decides the answer. Alone, the
    positive half answers ``True`` for any bare identifier — which is what an
    earlier draft shipped, and why a fabricated member added to both the list
    and its floor stayed green.

    What it does NOT prove: that the name is one anything would ever call. A
    third check was tried for that — "the subject does not already call it" —
    and dropped, because the real guard already forbids exactly that, so the
    assertion was satisfied by an upstream pin and deleting it reddened
    nothing. An unfalsifiable defence is the shape this file exists to catch.
    See "Known limits" in ``docs/standards/parametrised_guards/README.md``.
    """
    from tests.architecture.test_director_no_authority import called_names

    injected = (
        f"{_source_of(subject)}\n\ndef _witness(obj):\n    return obj.{member}()\n"
    )
    return member in (called_names(ast.parse(injected)) & deny_list)


def import_witness(subject: str, member: str, deny_list: frozenset[str]) -> bool:
    """The import guard's half of :func:`call_witness`, same contract."""
    from tests.architecture.test_director_no_authority import import_roots

    injected = f"{_source_of(subject)}\n\nimport {member}\n"
    return member in (import_roots(ast.parse(injected)) & deny_list)


#: Module-level frozensets in ``test_director_no_authority`` that are allow-lists
#: rather than deny-lists. An allow-list states a COMPLETE surface and is pinned
#: by equality against the live class, which is a stronger guard than a floor
#: and a different shape.
ALLOW_LIST_NAMES: frozenset[str] = frozenset({"ALLOWED_BROKER_METHODS"})


def declared_deny_lists() -> frozenset[str]:
    """Every module-level name-set in ``test_director_no_authority``.

    The derivation :data:`DENY_LIST_FLOORS` is pinned against, so a FIFTH
    deny-list cannot arrive unfloored. Without it the floors, the live-list map
    and the witness-subject map are three hand-written tables agreeing with
    each other — "did the author remember" one level up, which is the defect
    this module exists to remove.
    """
    from tests.architecture import test_director_no_authority as director

    # Names ASSIGNED in that module, read from its source — not ``vars()``,
    # which also returns what it imports. ``SPAWN_PRIMITIVES`` is a deny-list,
    # but it belongs to ``sandbox_seam_scan`` and is floored by that module's
    # own guards; claiming it here would be this registry reaching across a
    # boundary to protect something it does not own.
    tree = ast.parse(_source_of("tests/architecture/test_director_no_authority.py"))
    assigned: set[str] = set()
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        assigned.update(t.id for t in targets if isinstance(t, ast.Name))

    return frozenset(
        f"test_director_no_authority.{name}"
        for name in assigned
        if name not in ALLOW_LIST_NAMES
        and isinstance(value := getattr(director, name, None), (frozenset, set))
        and value
        and all(isinstance(member, str) for member in value)
    )


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
#: So the floor is a second copy of the vocabulary, in a second file, and the
#: enforced property is EQUALITY in both directions. ``floor <= live`` catches
#: the drop; the per-member sweep over ``live`` catches the addition, because
#: ``floor_protects`` answers False for a live member the floor does not
#: carry. Adding a member means adding it here too.
#:
#: Equality rather than containment, and the difference is not strictness for
#: its own sake. Under ``floor <= live`` alone, a member added after the floor
#: was written is absent from the floor, so dropping it again satisfies the
#: containment and reddens nothing — it is unprotected from arrival. The floor
#: would then cover a shrinking fraction of the list while passing: 15 of 30
#: names after fifteen additions. That is F2 reproduced inside the mechanism
#: built to catch F2, which is why the convenient reading is the bug.
#:
#: A second copy is the cost, and it is the price of a drop reddening at all:
#: two objects that must agree is the only arrangement where losing one is
#: visible, which is the same reason a ratchet baseline is a copy. What it
#: must NOT become is a copy nobody re-reads — hence the per-member witness
#: below, which exercises every live member through the guard's own extractor.
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

    Two shapes are seen: a bare module-level name, and a call to a
    module-level function (``registered_claims()``), which is how this repo
    usually spells a registry. Known blind spots, stated rather than implied:
    an imported name, and a comprehension over one. Both must be registered by
    hand — see "Known limits" in the standard.
    """
    found: list[GateSequence] = []
    root = repo_root()
    for path in sorted((root / SCAN_ROOT).glob("test_*.py")):
        if path.stem in SCAN_EXEMPT_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        bound: set[str] = set()
        # Defined here OR imported. Imported is the common case and the one
        # that matters: ``registered_claims`` lives in
        # ``vitals_conformance_registry`` and is imported by the test that
        # parametrises over it. Restricting this to local defs would have kept
        # the blind spot it was widened to close.
        defined: set[str] = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        } | {
            alias.asname or alias.name
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
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
                # A bare module-level name: ``parametrize("x", MEMBERSHIPS)``.
                if isinstance(arg, ast.Name) and arg.id in bound:
                    found.append(
                        GateSequence(
                            f"{path.stem}.{arg.id}", str(path.relative_to(root))
                        )
                    )
                # A module-level CALL: ``parametrize("x", registered_claims())``.
                # This repo's dominant idiom for a registry — four of them are
                # spelled that way — so a scan that saw only bare names would
                # be blind to the natural way of writing the next one, and
                # ``registered_claims()`` was already live and unclassified.
                elif (
                    isinstance(arg, ast.Call)
                    and isinstance(arg.func, ast.Name)
                    and arg.func.id in defined
                ):
                    found.append(
                        GateSequence(
                            f"{path.stem}.{arg.func.id}()",
                            str(path.relative_to(root)),
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
    from tests.architecture import vitals_conformance_registry as vitals

    decision_path = director.claiming_modules()
    actuators = director.brokered_actuator_modules()
    canaries = {row.name for row in canary_registry.discovered_canaries()}
    proposal_keys = proposal_keys_read_by_parser()
    # NOT re-derived from ``PlanRouteReason``: ``_PHASE_ROWS`` is derived from
    # that enum, so a detector reading the same enum would answer True for
    # every member by construction and detect nothing. ``REFUSAL_CODES`` is the
    # independently maintained object — a hand-written table keyed by those
    # members — so "this member still has a refusal row" is a real question
    # with a real answer. Two objects that must agree is the only arrangement
    # in which a drop reddens (``docs/standards/parametrised_guards``).
    refusal_rows = {reason.name for reason in plan_broker.REFUSAL_CODES}

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
            detects_drop=lambda member: member in refusal_rows,
            why=(
                "#11716 residue 1. ROLE_PHASE_FORBIDDEN claims the CATALOGUE "
                "forbids the role; a phase outside the canary's bound says "
                "nothing about the role. A dropped row stops the distinction "
                "being checked for that phase, and flipping it survives. The "
                "drop that matters is the REFUSAL_CODES row: a member with no "
                "row has no code to be wrong about."
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
                "across every decision-path module and every actuator. A new "
                "member goes in DENY_LIST_FLOORS here as well as in the list."
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
                "an actuator keep a second copy of the lap. A new member goes "
                "in DENY_LIST_FLOORS here as well as in the list."
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
                "apply its own fix' becomes a one-line change nothing reddens. "
                "A new member goes in DENY_LIST_FLOORS here as well."
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
                "guards, which know only sanctioned helper names. A new member "
                "goes in DENY_LIST_FLOORS here as well as in the list."
            ),
        ),
        GuardedEnumeration(
            name="test_admission_rule_tables.FENCING_WITNESSES",
            members=tuple(
                witness.reason.value for witness in admission.FENCING_WITNESSES
            ),
            kind=EnumerationKind.SUBJECT,
            detects_drop=admission.fencing_row_is_reachable,
            undetected_members={
                "role_not_in_catalog": (
                    "admit_dispatch re-derives this reason below the table as "
                    "a type narrowing, so the witness is answered identically "
                    "with the row deleted. Caught instead by "
                    "test_the_witnesses_are_the_table_in_order, which compares "
                    "the AST-extracted row order against the witness tuple."
                )
            },
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
        GuardedEnumeration(
            name="test_vitals_conformance_seam.registered_claims()",
            members=tuple(claim.name for claim in vitals.registered_claims()),
            kind=EnumerationKind.SUBJECT,
            why=(
                "A dropped row stops an artifact being classified vitals or "
                "conformance, so nothing checks that a rule which must be "
                "answerable offline still is — 'a conformance check that stops "
                "running must fail, not pass', unenforced for that artifact."
            ),
            undetected_reason=(
                "The derivation is 'every gate and artifact in the repo', "
                "which that registry documents as manual on purpose. Same "
                "shape as MEMBERSHIPS: a registry of registries, and its own "
                "open problem rather than this gate's. Surfaced here by the "
                "scan rather than by anyone remembering, which is the scan "
                "doing its job."
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
