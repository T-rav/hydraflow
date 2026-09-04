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

import yaml

from pytest_collection import collected_test_globs, is_collected_test_file

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Iterable, Mapping

__all__ = [
    "ALLOW_LIST_NAMES",
    "DERIVED_SUBJECT_NAMES",
    "DENY_LIST_FLOORS",
    "EnumerationKind",
    "call_witness",
    "declared_deny_lists",
    "floor_protects",
    "IMPORT_BOUNDARY_FLOOR",
    "import_boundary_denials",
    "os_witness",
    "GuardedEnumeration",
    "GRANDFATHERED_UNCLASSIFIED",
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


def os_witness(subject: str, member: str, deny_list: frozenset[str]) -> bool:
    """The ``os``-qualified guard's half of :func:`call_witness`.

    ``reachable_os_spawns`` is the third extractor in this file's guard, added
    by #11724: it matches an attribute of a Name bound to ``os``, so its
    witness injects ``os.<member>()`` rather than a bare call or an import.

    The member is compared against the ATTRIBUTE half of the dotted result,
    because the extractor reports ``os.system`` where the deny-list carries
    ``system`` — precisely the shape mismatch
    ``test_the_guard_can_actually_see_every_denied_name`` exists to catch, and
    the reason that comparison is spelled out here rather than assumed.

    Works for ``_OS_SPAWN_PREFIXES`` as well as ``_OS_SPAWN_EXACT``: every
    prefix is a prefix of itself, so injecting ``os.exec()`` is the minimal
    witness that the ``exec`` rule fires at all.

    **NOT the same contract as its two siblings, and the difference decides
    how the negative control has to be written.** ``called_names`` and
    ``import_roots`` are maximally permissive — they record ANY call name and
    ANY import root — so for those the extractor always answers yes and the
    ``& deny_list`` step is what answers no. ``reachable_os_spawns`` is gated
    internally by ``_is_os_spawn``, which reads the very sets this function is
    handed as ``deny_list``. A name the list does not carry is therefore
    rejected by the EXTRACTOR, before the intersection is consulted.

    So ``& deny_list`` is not load-bearing against an arbitrary name here, and
    an earlier version of this file proved it: deleting the intersection left
    every test green. It is kept because it is the correct expression of the
    contract, and it is made falsifiable by ``_UNDENIED_OVERRIDES`` in the
    gate, which feeds each ``os`` row a name the extractor DOES flag and the
    row's own list does not carry.
    """
    from tests.architecture.test_director_no_authority import reachable_os_spawns

    injected = (
        f"{_source_of(subject)}\n\nimport os\n\n"
        f"def _witness():\n    return os.{member}()\n"
    )
    seen = {
        dotted.split(".", 1)[1] for dotted in reachable_os_spawns(ast.parse(injected))
    }
    return member in (seen & deny_list)


#: Module-level frozensets in ``test_director_no_authority`` that are allow-lists
#: rather than deny-lists. An allow-list states a COMPLETE surface and is pinned
#: by equality against the live class, which is a stronger guard than a floor
#: and a different shape.
ALLOW_LIST_NAMES: frozenset[str] = frozenset({"ALLOWED_BROKER_METHODS"})

#: Module-level name-sequences in ``test_director_no_authority`` that are
#: SUBJECTS with their own derivation, not deny-lists. ``DECISION_PATH_MODULES``
#: is pinned by ``claiming_modules() == literal``, which is strictly stronger
#: than a floor: a floor catches a drop, an equality catches a drop AND an
#: unlisted addition.
#:
#: A second named exemption rather than a broader type test, because the
#: distinction is not one the container type can carry — see
#: :func:`declared_deny_lists`.
DERIVED_SUBJECT_NAMES: frozenset[str] = frozenset({"DECISION_PATH_MODULES"})


def declared_deny_lists() -> frozenset[str]:
    """Every module-level name-sequence in ``test_director_no_authority`` that
    no other mechanism accounts for.

    The derivation :data:`DENY_LIST_FLOORS` is pinned against, so a FIFTH
    deny-list cannot arrive unfloored. Without it the floors, the live-list map
    and the witness-subject map are three hand-written tables agreeing with
    each other — "did the author remember" one level up, which is the defect
    this module exists to remove.

    **Container type is not the discriminator, and assuming it was is how this
    derivation went blind (#11724).** The first version matched ``frozenset``
    and ``set`` only. ``_OS_SPAWN_PREFIXES`` is spelled as a tuple — it feeds
    ``str.startswith``, which requires one — so it was a deny-list of exactly
    the same kind sitting outside the mechanism that floors the other five,
    and nothing reddened to say so. That is the enumeration-by-spelling defect
    this gate exists to catch, reproduced inside the gate: the next author to
    reach for a tuple would have concluded their list was covered.

    So the sweep is over every non-empty sequence of strings, and what
    separates a deny-list from a subject is stated as a named exemption
    (:data:`ALLOW_LIST_NAMES`, :data:`DERIVED_SUBJECT_NAMES`) rather than
    inferred from how it is written. An unexempt, unfloored name-set is a hard
    red, which is the only arrangement where the author of the NEXT one finds
    out.
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

    exempt = ALLOW_LIST_NAMES | DERIVED_SUBJECT_NAMES
    return frozenset(
        f"test_director_no_authority.{name}"
        for name in assigned
        if name not in exempt
        and isinstance(
            value := getattr(director, name, None), (frozenset, set, tuple, list)
        )
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
    # #11724's two. `_OS_SPAWN_PREFIXES` carries prefixes rather than whole
    # attribute names: `exec` floors the entire `os.exec*` family, so dropping
    # it silently un-denies eight spellings at once (execl, execle, execlp,
    # execlpe, execv, execve, execvp, execvpe).
    "test_director_no_authority._OS_SPAWN_EXACT": frozenset({"startfile", "system"}),
    "test_director_no_authority._OS_SPAWN_PREFIXES": frozenset(
        {"exec", "fork", "popen", "posix_spawn", "spawn"}
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


#: Shrink-only floor for the declared import boundaries, keyed
#: ``<boundary>::<denied module>``.
#:
#: Same shape and same reason as :data:`DENY_LIST_FLOORS` above, one level out:
#: an import deny-list cannot be derived, because most of what it denies
#: appears nowhere in this repo — that is the point of denying it. So the floor
#: is a second copy of the vocabulary, in a second file, and the enforced
#: property is EQUALITY in both directions
#: (``test_the_denial_floor_and_the_declarations_agree``). Containment alone
#: would leave a denial added after the floor was written unprotected from
#: arrival.
#:
#: One flat key space rather than two tables, because a boundary dropped whole
#: and a single denial dropped from one boundary are the same loss: the rule
#: silently stops being enforced and every guard over it stays green.
#:
#: ``concurrent.futures`` joined with #11753's fix and is floored from the
#: start — the pin it replaces could not express it, so a drop back to the two
#: stdlib roots would be that bug restored with the fix still in the file.
IMPORT_BOUNDARY_FLOOR: frozenset[str] = frozenset(
    {
        "no-otel-under-src::opentelemetry",
        "no-otel-under-src::telemetry.otel",
        "no-otel-under-src::telemetry.slugs",
        "no-otel-under-src::telemetry.spans",
        "no-otel-under-src::telemetry.subprocess_bridge",
        "no-scripts-at-boot-under-src::scripts",
        "no-spawn-machinery-on-the-decision-path::concurrent.futures",
        "no-spawn-machinery-on-the-decision-path::multiprocessing",
        "no-spawn-machinery-on-the-decision-path::subprocess",
    }
)


def import_boundary_denials(live: Iterable[str], member: str) -> bool:
    """Would dropping *member* from the live denial set break its floor?

    The registry's ``detects_drop`` for the declared import boundaries. Runs
    the real comparison over the real objects rather than asserting either is
    present: a member the floor does not carry is a member whose removal
    nothing would notice, and this answers ``False`` for it.
    """
    return not (set(live) - {member}) >= IMPORT_BOUNDARY_FLOOR


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


#: Sequences still unclassified after the scan was widened from
#: ``tests/architecture`` (120 files) to every test file pytest collects (1955).
#:
#: The widening surfaced 94. Fifty were classified in the same change, because
#: their answer was mechanical and therefore honest to give in bulk: 28 corpora
#: (synthetic inputs fed to a detector) and 22 sequences that are COMPUTED at
#: import rather than typed out, which cannot lose a member to an omission.
#:
#: The 44 left are the ones that actually matter — hand-typed literal
#: collections, which is the exact shape that failed here. Each needs a
#: drop-detector reasoned about on its own, and generating 44 of those at once
#: would produce 44 justifications nobody read, which is the failure this
#: registry exists to prevent. They shrink as they are worked, one at a time.
#:
#: Shrink-only in BOTH directions: nothing may be added, and an entry that
#: becomes classified or disappears must be removed —
#: ``test_the_grandfathered_backlog_only_shrinks`` refuses a standing exemption
#: for a name that no longer needs one.
GRANDFATHERED_UNCLASSIFIED: frozenset[str] = frozenset(
    {
        "regression_issue_6668.OFFENDING_FILES",
        "regression_issue_6752.KNOWN_UNGUARDED_SITES",
        "regression_issue_6766.KNOWN_UNGUARDED_SITES",
        "regression_issue_6809.KNOWN_UNGUARDED_SITES",
        "regression_issue_6814.KNOWN_UNGUARDED_SITES",
        "regression_issue_6855.KNOWN_UNGUARDED_SITES",
        "test_async_subprocess_timeouts._ASYNC_SUBPROCESS_MODULES",
        "test_audit_packaged_src_layout_11709._NOT_UI_TEST_PATHS",
        "test_audit_packaged_src_layout_11709._ORCHESTRATION_MARKERS",
        "test_audit_packaged_src_layout_11709._UI_TEST_PATHS",
        "test_auto_agent_decompose_terminal._LANDED_FIX_READS",
        "test_collaborator_wiring._COLLABORATOR_WIRING_TABLE",
        "test_composition_root_runner_seams_11602.SEAMED_LOOPS",
        "test_config_validation._BOUNDED_INT_FIELDS",
        "test_dashboard_routes_scheduling._STATUS_FLAGS",
        "test_director_turn_runner_env._EXPECTED_ENV",
        "test_exception_chaining.BUG_EXCEPTIONS",
        "test_factory_image_trigger_scope._PROTECTED",
        "test_fake_docker_contract.list_cassettes()",
        "test_fake_git_contract.list_cassettes()",
        "test_fake_github_contract.list_cassettes()",
        "test_fake_workspace_contract._PORT_METHODS",
        "test_hydraflow_audit_layout._BUILD_BACKENDS",
        "test_issue_11004_agent_image_extras._AGENT_DOCKERFILES",
        "test_issue_11533_stale_driver_states.RETIRED_STATES",
        "test_issue_11691_beads_runtime_ignored._RUNTIME_PATHS",
        "test_issue_6438._KNOWN_VIOLATIONS",
        "test_issue_6513.AFFECTED_FILES",
        "test_issue_6983.KNOWN_UNGUARDED_SITES",
        "test_issue_9454._UNHARDENED_COMMUNICATE_MODULES",
        "test_issue_9540._SPAWN_CONTRACT_FILES",
        "test_issue_9579._GROUP_REAP_SITES",
        "test_issue_9579._HEAVY_SPAWN_SITES",
        "test_issue_store_queue_strategy._ALL_STAGES",
        "test_mockworld_fakes_conformance._PORT_FAKE_PAIRS",
        "test_mockworld_fakes_conformance._REAL_RUNNER_FAKE_ATTRS",
        "test_mockworld_fakes_conformance._REAL_RUNNER_PORT_PAIRS",
        "test_mockworld_fakes_marker._FAKE_CLASSES",
        "test_nodesource_fetch_retry_10740._AGENT_DOCKERFILES",
        "test_self_repair_on_by_default.EXCLUDED_OFF_FLAGS",
        "test_self_repair_on_by_default.OPT_IN_AFTER_CACHE_FLAGS",
        "test_self_repair_on_by_default.SELF_REPAIR_FLAGS",
        "test_shape_dispatchers.COVERED_ARGS",
        "test_shape_dispatchers.UNCOVERED_ARGS",
    }
)


#: Why a CORPUS needs no drop-detector, stated once instead of twenty-eight
#: times. Taken from the standard's own definition: a corpus is the guard's
#: EVIDENCE — synthetic inputs fed to a detector to prove it sees each shape.
#: Dropping a member drops a test case, which narrows a proof; it does not
#: narrow what the gate is asked about. That is a coverage question, and it is
#: a different question from a SUBJECT losing a member, where the gate silently
#: stops covering something that is still there.
_CORPUS_IS_EVIDENCE = (
    "Evidence, not subject: each member is one input shape fed to the "
    "detector under test, and the assertion is made per case rather than "
    "over the list, so dropping one narrows the proof without weakening the "
    "property into a vacuous pass."
)


#: Why a sequence produced by a CALL needs no drop-detector. It is computed at
#: import from the tree or the filesystem, so it cannot lose a member by
#: somebody forgetting to add one — the failure mode this registry exists for.
#: Losing a member here means the producer stopped finding something, which the
#: producer's own anti-vacuity check is responsible for.
_DERIVED_CANNOT_GO_STALE = (
    "Derived, not typed: the members are computed at import rather than "
    "listed, so a member cannot go missing through an omission. A shrinking "
    "result means the producer stopped seeing its source, which is a question "
    "for the producer's own floor, not for a hand-maintained row here."
)


def _scanned_test_files(root: Path) -> tuple[Path, ...]:
    """Every test file pytest collects under ``tests/``, not one directory of them.

    This scan used to be ``(root / "tests/architecture").glob("test_*.py")`` —
    120 of the 1955 files pytest actually collects, about six per cent. The gate
    whose entire purpose is catching a guarded set narrower than its subject was
    itself the narrowest kind: one directory, non-recursive, and one filename
    spelling.

    It cost something real. ``tests/regressions/test_issue_11803_one_flow_stopped.py``
    parametrised a hand-typed tuple of three phase modules; ``src/triage_phase.py``
    held a fourth copy of the guard for months, outside the list and therefore
    outside the gate. 637 of the unscanned files were under ``tests/regressions/``.

    The membership predicate is ``pytest_collection``'s, the same one
    ``test_every_test_the_standard_names_exists`` already uses, so this cannot
    drift from what pytest collects — and it does not repeat that module's
    mistake of a second hardcoded ``test_*.py``, which would still be blind to
    the ``regression_*.py`` files this repo really does collect.
    """
    globs = collected_test_globs(root)
    return tuple(
        sorted(
            path
            for path in (root / "tests").rglob("*.py")
            if is_collected_test_file(path.name, globs)
        )
    )


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
    for path in _scanned_test_files(root):
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
    import routing_baseline
    from tests import (
        test_adequacy_demand,
        test_claude_hook_shell_tests,
        test_events,
        test_gateway_conformance,
        test_hydraflow_audit_layout,
        test_loops_smoke,
        test_no_screenshot_regression_tests,
        test_no_shadow_imports,
        test_provider_dial_parity_baseline,
        test_review_insights,
        test_sandbox_scenario_contract,
        test_worker_receipts,
    )
    from tests import (
        test_generated_lock_refuses_a_literal as generated_lock,
    )
    from tests.architecture import aggregate_gate_registry as aggregate_lane
    from tests.architecture import canary_registry
    from tests.architecture import test_admission_rule_tables as admission
    from tests.architecture import test_audit_src_layout_ratchet as src_layout
    from tests.architecture import test_canary_family_conformance as canary_sweep
    from tests.architecture import (
        test_change_chain_no_agent_write_path as chain_write_path,
    )
    from tests.architecture import test_director_no_authority as director
    from tests.architecture import test_fatal_exception_set_centralized as fatal
    from tests.architecture import test_import_boundary_gate as boundaries
    from tests.architecture import test_kernel_documents_live_in_files as kernel_docs
    from tests.architecture import test_mockworld_loop_scenario_ratchet as mockworld
    from tests.architecture import test_path_membership_registry as membership
    from tests.architecture import test_policy_charter_parity as charter_parity
    from tests.architecture import test_policy_engine_is_pure as policy_purity
    from tests.architecture import test_producer_probe_gate as probe_gate
    from tests.architecture import test_provider_dial_source_map as dial_sources
    from tests.architecture import (
        test_readme_model_dials_exist as readme_model_dials,
    )
    from tests.architecture import test_standards_rules_are_wired as rules_wired
    from tests.architecture import (
        test_ungoverned_spawn_faces as ungoverned_faces,
    )
    from tests.architecture import (
        test_worker_lineage_reaches_the_mint as worker_lineage,
    )
    from tests.auto_agent.adversarial import test_corpus
    from tests.evals import test_term_proposer_evals, test_triage_honeypot_evals
    from tests.regressions import (
        regression_issue_10094,
        test_anchor_whitespace_is_not_content,
        test_audit_packaged_src_layout_11709,
        test_container_images_are_multi_arch,
        test_issue_9566,
        test_issue_10440,
        test_issue_10870,
        test_issue_11180,
        test_issue_11481_closing_verb_class,
        test_issue_11669_self_mod_veto_follows_package,
        test_issue_11803_one_flow_stopped,
        test_issue_11891_fields_reach_their_producer,
        test_issue_11939_port_fake_name_is_a_hint,
        test_issue_11969_mirror_pins_are_real,
        test_issue_12144_llm_seam_fails_closed,
    )
    from tests.regressions import (
        test_mirrored_mixin_seam_signatures as mirrored_seams,
    )
    from tests.sandbox_scenarios.runner import test_scenarios
    from tests.scenarios import (
        test_auto_agent_playbook_routing,
        test_loop_health,
        test_sandbox_parity,
    )
    from tests.trust.adversarial import test_adversarial_corpus
    from tests.trust.contracts import (
        test_cassette_surface_parity,
        test_fake_llm_contract,
    )

    def _standard_declares_rules(member: str) -> bool:
        """Does this standard still carry a `rules:` block? False if it is gone."""
        path = rules_wired.STANDARDS / member / "standard.yaml"
        if not path.is_file():
            return False
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return bool(data.get("rules"))

    def _probe_drop_is_caught(member: str) -> bool:
        """Dropping a probe breaches the shrink-only unprobed-producer ratchet.

        Independent of the gate's own populated/excused check: the subject is
        derived from the modules that actually serialise a model to disk, and
        removing a probe raises the unprobed count past its baseline.
        """
        spec = next((p for p in probe_gate.PROBES if p.name == member), None)
        if spec is None:
            return False
        return spec.module in probe_gate.persisting_producers()

    from tests.architecture import test_ratchet_baseline_keys_resolve as baselines
    from tests.architecture import test_runtime_caches_not_tracked as caches
    from tests.architecture import test_shell_spawn_lint_rules as shell_lint
    from tests.architecture import test_wiki_runtime_caches_untracked as wiki_caches
    from tests.architecture import vitals_conformance_registry as vitals

    decision_path = director.claiming_modules()
    # The live denial vocabulary, flattened. Read once so the two rows below
    # compare against ONE live object and the floor is the other — the
    # arrangement in which losing a member is visible at all.
    boundary_denials = boundaries.denial_ids()

    def _boundary_drop_is_caught(member: str) -> bool:
        """Dropping a whole boundary takes every denial it carried with it."""
        surviving = {
            entry for entry in boundary_denials if not entry.startswith(f"{member}::")
        }
        return not surviving >= IMPORT_BOUNDARY_FLOOR

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
    # The Makefile's copy of the ungated aggregate-ratchet lane — a
    # different object from AGGREGATE_GATES, read out of a different file,
    # and the one that actually runs in CI and locally. A member dropped
    # from the Python registry stops appearing here, which is a real
    # question with a real answer rather than two views of one list.
    makefile_lane = set(aggregate_lane.makefile_lane_paths())
    # Read out of pyproject.toml, NOT out of the test's own tuple: the rules
    # ruff is actually configured to run. A rule dropped from `_RULES` while
    # still selected is a rule nobody has watched fire; one selected without
    # a test is a rule with no falsifying example. Two objects that must
    # agree, which is the only arrangement in which a drop reddens.
    selected_shell_rules = shell_lint.selected_shell_spawn_rules()
    # The loop classes named by a HAND-WRITTEN catalog builder in
    # tests/scenarios/catalog/loop_registrations.py — NOT re-derived from
    # extract_loops, which is where LOOP_CLASS_NAMES comes from. Two sets
    # derived from one source agree by construction and detect nothing; this
    # one is maintained by hand and kept honest against
    # orchestrator.bg_loop_registry by test_catalog_completeness, so "does
    # this loop still have a builder?" is a real question with a real answer.
    loop_builder_classes = mockworld.builder_reachable_classes()

    # The .py files actually on disk under src/policy/, read by rglob — NOT
    # re-derived from _PURE_SOURCES. Dropping a source from the pin leaves its
    # file unclassified, which the live _delta reports; two objects that must
    # agree, so a drop reddens.
    policy_modules_on_disk = {
        path.relative_to(policy_purity.REPO).as_posix()
        for path in (policy_purity.REPO / policy_purity._POLICY_PACKAGE).rglob("*.py")  # noqa: SLF001
    }

    def _worker_lineage_drop_is_caught(member: object) -> bool:
        """Would dropping this case stop the guard seeing a runner?

        Runs the LIVE sweep rather than a copy of it: the anti-vacuity test
        asserts the three known runners are still found, so a case whose module
        disappears from the discovered set is caught there. A second case in an
        already-covered module is a coverage loss, not a blind spot, and the
        module-level assertion cannot see it — which is exactly what this
        returns False for.
        """
        if not (isinstance(member, tuple) and len(member) == 3):
            # A member this subject has never carried: answer no, rather than
            # crashing or claiming a drop nobody could have made.
            return False
        module, _func, _passed = member
        remaining = {
            other
            for other, _f, _p in worker_lineage._CASES
            if other != module  # noqa: SLF001
        }
        return module not in remaining

    def _ungoverned_face_drop_is_caught(member: object) -> bool:
        """Would dropping this face stop the guard asking about it?

        A member of this subject is a face the guard REFUSES unless it is
        registered, so dropping one removes a refusal rather than a coverage
        row. The live sweep is re-run: if the path no longer appears among the
        literal non-gateway faces, it is genuinely gone from the tree; if it
        still appears, the drop was from the parametrise list alone and the
        gate would stop asking about a face that is still there.
        """
        if not (isinstance(member, tuple) and len(member) == 3):
            return False
        path, _line, _value = member
        return path in {p for p, _l, _v in ungoverned_faces.UNGOVERNED_FACES}

    def _baseline_dial_drop_is_caught(member: str) -> bool:
        """A dial dropped from the generator's maps reddens the parity gate.

        `_GENERATABLE` derives from `routing_baseline._PRINCIPAL_DIALS` and
        `_PRINCIPAL_DIALS`, and the generator's own
        `test_every_dial_is_either_generated_or_registered_as_a_gap` compares
        their union with `UNGENERATED_DIALS` against every `*_provider` field
        on `HydraFlowConfig`. Removing a dial from either map shrinks the
        covered set while the config is unchanged, so the equality fails and
        names the dial.
        """
        from config import HydraFlowConfig  # noqa: PLC0415

        return member in HydraFlowConfig.model_fields

    def _hydraflow_config() -> type:
        from config import HydraFlowConfig  # noqa: PLC0415

        return HydraFlowConfig

    def _gateway_dial_drop_is_caught(member: str) -> bool:
        """A dial dropped from the routing guard reddens its capable-set case.

        `_DIALS` derives from `HydraFlowConfig`'s own `*_provider` fields, and
        `test_the_capable_set_covers_every_dial` asserts that set equals
        `GATEWAY_CAPABLE_PROVIDER_FIELDS`. A dial that stopped being a field
        would drop out of both sides at once, so the equality is not what
        catches it — `test_there_are_dials_to_guard`'s floor is, which is why
        that floor tracks the real count rather than carrying slack.
        """
        from config import HydraFlowConfig  # noqa: PLC0415

        return member in HydraFlowConfig.model_fields

    def _required_prompt_root_drop_is_caught(member: str) -> bool:
        """A dropped root leaves real prompt files unrequired by the sweep.

        Witnessed against the FILESYSTEM, not against PROMPT_ROOTS: the
        latter is a superset of REQUIRED_ROOTS by construction, so reading
        it answers True for every member and certifies nothing. The real
        question is whether the tree still holds prompts that would stop
        being required — which is what the per-root test asserts.
        """
        root = chain_write_path.REPO_ROOT / member  # noqa: SLF001
        if not root.is_dir():
            return False
        return any(
            path.is_file() and path.suffix in chain_write_path.PROMPT_SUFFIXES  # noqa: SLF001
            for path in root.rglob("*")
        )

    def _policy_purity_drop_is_caught(member: str) -> bool:
        classified = (
            set(policy_purity._PURE_SOURCES) | set(policy_purity._IO_SOURCES)  # noqa: SLF001
        ) - {member}
        unclassified, _missing = policy_purity._delta(  # noqa: SLF001
            policy_modules_on_disk, classified
        )
        if member in unclassified:
            return True
        # A pinned source OUTSIDE src/policy/ (charter_model, and the
        # vocabulary module it imports) is not on the policy rglob, so the
        # classification delta above cannot see it leave. Its witness is
        # test_first_party_dependencies_are_pinned_pure_or_declared_mixed: a
        # pure source still imports it, and it is not a declared mixed
        # dependency, so dropping it from the pin reddens there instead.
        for modules in policy_purity._PURE_IMPORTS.values():  # noqa: SLF001
            for dotted in modules:
                if policy_purity._first_party_path(dotted) == member:  # noqa: SLF001
                    return dotted not in policy_purity._MIXED_DEPENDENCIES  # noqa: SLF001
        return False

    def _trust_fleet_mixin_drop_is_caught(member: str) -> bool:
        """A mixin dropped from ``HydraFlowConfig``'s bases takes its dials with it.

        ``MIXINS`` is derived from ``HydraFlowConfig.__bases__``, so a mixin
        that stops being a base leaves the sweep and the config in the same
        motion — every parametrised case over it simply stops running, which is
        the vacuity this registry exists to notice. The witness is
        ``test_all_three_mixins_are_bases_of_the_config``, which asserts the
        derived set equals the three classes named explicitly, so a drop is an
        inequality rather than a silently shorter sweep.

        Checked here the way the gateway-dial detector checks its own: confirm
        the member is genuinely part of the live derivation — its declared
        dials really are on ``HydraFlowConfig`` — so removing it is something
        ``model_fields`` and the named-set assertion can both see.
        """
        import config_trust_fleet_dials as dials  # noqa: PLC0415

        cls = getattr(dials, member, None)
        if cls is None:
            # A name that was never a mixin is not a drop this guard catches —
            # answering True here would make the detector vacuous, which the
            # gate's own never-there meta-test exists to notice.
            return False
        declared = set(cls.model_fields)
        return bool(declared) and declared <= set(_hydraflow_config().model_fields)

    return (
        # --- SUBJECTS, derived ------------------------------------------
        GuardedEnumeration(
            name="test_config_trust_fleet_dials.MIXINS",
            members=(
                "TrustFleetHealthDials",
                "TrustFleetSteeringDials",
                "TrustFleetVocabularyDials",
            ),
            kind=EnumerationKind.SUBJECT,
            detects_drop=_trust_fleet_mixin_drop_is_caught,
            why=(
                "#11547's config decomposition. The trust-fleet dials moved "
                "off HydraFlowConfig onto three mixins, and every case that "
                "checks the move held — fields present, defaults and "
                "constraints surviving inheritance, no mixin over the "
                "god-class threshold — is parametrised over the config's own "
                "__bases__. A mixin dropped from those bases therefore leaves "
                "the sweep at the same instant it leaves the config, so the "
                "cases do not fail, they stop existing. "
                "test_all_three_mixins_are_bases_of_the_config pins the "
                "derived set against the three classes by name, which is what "
                "turns that silence into a red."
            ),
        ),
        GuardedEnumeration(
            name="test_routing_baseline_generator._GENERATABLE",
            members=tuple(sorted(routing_baseline._PRINCIPAL_DIALS)),  # noqa: SLF001
            kind=EnumerationKind.SUBJECT,
            detects_drop=_baseline_dial_drop_is_caught,
            why=(
                "#11991 P6b's generator. Every parity case is parametrised over "
                "this tuple, so a dial dropped from it stops having its "
                "generated policy resolved against what the dial produces "
                "today — and the whole point of the migration is that a dial "
                "which stops steering does not raise, it routes to a default "
                "that looks reasonable (#11853's shape). The drop is caught by "
                "test_every_dial_is_either_generated_or_registered_as_a_gap, "
                "which compares the maps against HydraFlowConfig's own fields."
            ),
        ),
        GuardedEnumeration(
            name="test_every_dial_routes_through_the_gateway._DIALS",
            members=tuple(
                sorted(
                    n
                    for n in _hydraflow_config().model_fields
                    if n.endswith("_provider")
                )
            ),
            kind=EnumerationKind.SUBJECT,
            detects_drop=_gateway_dial_drop_is_caught,
            why=(
                "ADR-0147's routing guard. Every case is parametrised over the "
                "dials themselves, so a dial dropped from the sweep stops "
                "having its gateway default asserted — and an unrouted dial "
                "does not raise, it spends on a lane the ledger never sees, "
                "which is the exact blindness ADR-0147 exists to end. The "
                "floor in test_there_are_dials_to_guard catches the drop."
            ),
        ),
        GuardedEnumeration(
            name="test_mirrored_mixin_seam_signatures._MIRRORED",
            members=tuple(mirrored_seams._MIRRORED),  # noqa: SLF001
            kind=EnumerationKind.CORPUS,
            why=(
                "Every mixin method declared in one file as a TYPE_CHECKING "
                "stub and implemented in another. The mismatch it catches is "
                "invisible at runtime — the stub never executes, so no test "
                "can call the difference into failure, only a type checker. "
                "Derived from source by AST at import, not listed, so the "
                "producer's own floor is what guards the population: "
                "test_the_sweep_found_mirrored_seams (non-empty) and "
                "test_the_known_regression_subject_is_in_the_set (the seam "
                "whose stale mirror this exists for)."
            ),
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_change_chain_no_agent_write_path._prompt_files()",
            members=tuple(
                chain_write_path._relative(path)  # noqa: SLF001
                for path in chain_write_path._prompt_files()  # noqa: SLF001
            ),
            kind=EnumerationKind.CORPUS,
            why=(
                "ADR-0149's security property: the artifact chain is written "
                "by the harness and never by an agent, so no prompt may name "
                "docs/changes/. Each member is one prompt file the needle runs "
                "against, asserted per case — dropping one narrows the proof, "
                "it does not make the rule vacuous. The POPULATION is guarded "
                "per root by "
                "test_each_required_prompt_root_still_contributes_files, which "
                "is what reddens when a root moves and its files stop being "
                "swept."
            ),
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_change_chain_no_agent_write_path.REQUIRED_ROOTS",
            members=tuple(str(root) for root in chain_write_path.REQUIRED_ROOTS),
            kind=EnumerationKind.SUBJECT,
            detects_drop=_required_prompt_root_drop_is_caught,
            why=(
                "The roots that must keep contributing files to the prompt "
                "sweep. This IS the population check: dropping a root stops "
                "that tree being required, which is how half the corpus could "
                "leave the sweep while it stayed green. Witnessed against the "
                "prompt roots actually present on disk, not against "
                "PROMPT_ROOTS — a superset literal would answer True for "
                "every member and certify a detection that does not exist."
            ),
        ),
        GuardedEnumeration(
            name="test_policy_engine_is_pure._PURE_SOURCES",
            members=tuple(policy_purity._PURE_SOURCES),  # noqa: SLF001
            kind=EnumerationKind.SUBJECT,
            detects_drop=_policy_purity_drop_is_caught,
            why=(
                "Epic #11752's decision-engine seam. Every rule in that file "
                "iterates this tuple, so a dropped entry stops being checked "
                "for impure imports, import-free world reads (open, "
                "__import__, __file__), builtin shadowing and eval-able "
                "annotations all at once — while the module keeps sitting in "
                "src/policy/ looking guarded. The drop is caught by "
                "test_every_policy_module_is_classified, which compares the "
                "pin against the files actually on disk."
            ),
        ),
        GuardedEnumeration(
            name="test_worker_lineage_reaches_the_mint._CASES",
            members=worker_lineage._CASES,  # noqa: SLF001
            kind=EnumerationKind.SUBJECT,
            detects_drop=_worker_lineage_drop_is_caught,
            why=(
                "#11990's brokered-child seam. Every runner that builds a "
                "WorkerLineage must hand its spawn seam the child id it will "
                "claim and the driver that asked for it; a dropped case stops "
                "a runner being asked, and it keeps sitting in src/ minting "
                "keys under an id no receipt shares. The set is discovered by "
                "sweeping src/*_worker_runner.py, so the drop is caught by "
                "test_the_sweep_found_the_runners_it_was_built_from, which "
                "holds the sweep to the three runners it was built from."
            ),
        ),
        GuardedEnumeration(
            name="test_ungoverned_spawn_faces.UNGOVERNED_FACES",
            members=ungoverned_faces.UNGOVERNED_FACES,
            kind=EnumerationKind.SUBJECT,
            detects_drop=_ungoverned_face_drop_is_caught,
            why=(
                "#11544's one-shot half. A literal provider= at a spawn site "
                "is a face no dial can move, so an operator locking a "
                "repository to one provider cannot redirect it and the lock "
                "stops being true. Every such face must be registered with a "
                "reason; a dropped member stops being asked for one. The set "
                "is swept from the tree by AST, so the drop is caught by "
                "re-running that sweep."
            ),
        ),
        GuardedEnumeration(
            name="test_generated_lock_refuses_a_literal._LITERALS",
            members=tuple(generated_lock._LITERALS),  # noqa: SLF001
            kind=EnumerationKind.CORPUS,
            why=(
                "The two literal Anthropic models #11993 names as the "
                "non-negotiable — 'a literal Opus/Sonnet requirement is never "
                "silently rewritten to GLM'. They are examples the refusal is "
                "exercised with, not the population being guarded: the subject "
                "is `anthropic_lane_required`'s rule, which the generator's own "
                "empty `requirement_map` assertion covers directly. Dropping "
                "one leaves the rule still checked, with one fewer example."
            ),
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_readme_model_dials_exist._listed_loops()",
            members=tuple(readme_model_dials._listed_loops()),  # noqa: SLF001
            kind=EnumerationKind.CORPUS,
            why=(
                "The loop names README.md itself lists as having a model dial. "
                "CORPUS rather than SUBJECT because the members are READ FROM "
                "the subject: when a name leaves that sentence the README no "
                "longer claims the dial, so the gate is not silently failing to "
                "cover something still asserted. Pruning four dead names "
                "(sentry, code_grooming, memory_judge, memory_compaction) is "
                "what this guard was added to force, and a classification that "
                "reddened on it would punish the fix."
            ),
            undetected_reason=(
                "Evidence, not subject: each member is one claim the README "
                "makes, asserted per case. The vacuous end — an emptied list "
                "asserting nothing — is held by "
                "test_readme_model_dials_exist.test_the_list_is_not_empty."
            ),
        ),
        GuardedEnumeration(
            name="test_adequacy_demand.ANCHORED_CORPUS",
            members=tuple(str(item) for item in test_adequacy_demand.ANCHORED_CORPUS),
            kind=EnumerationKind.CORPUS,
            why="Cases test_adequacy_demand feeds its detector: anchored corpus.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_adequacy_demand.UNANCHORED_CORPUS",
            members=tuple(str(item) for item in test_adequacy_demand.UNANCHORED_CORPUS),
            kind=EnumerationKind.CORPUS,
            why="Cases test_adequacy_demand feeds its detector: unanchored corpus.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_anchor_whitespace_is_not_content.ANCHORS",
            members=tuple(
                str(item) for item in test_anchor_whitespace_is_not_content.ANCHORS
            ),
            kind=EnumerationKind.CORPUS,
            why="Cases test_anchor_whitespace_is_not_content feeds its detector: anchors.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_anchor_whitespace_is_not_content.BLANKS",
            members=tuple(
                str(item) for item in test_anchor_whitespace_is_not_content.BLANKS
            ),
            kind=EnumerationKind.CORPUS,
            why="Cases test_anchor_whitespace_is_not_content feeds its detector: blanks.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_audit_packaged_src_layout_11709._CONFORMANT_EXPECTATIONS",
            members=tuple(
                str(item)
                for item in test_audit_packaged_src_layout_11709._CONFORMANT_EXPECTATIONS
            ),
            kind=EnumerationKind.CORPUS,
            why="Cases test_audit_packaged_src_layout_11709 feeds its detector: conformant expectations.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_audit_packaged_src_layout_11709._CONTENT_VERDICTS",
            members=tuple(
                str(item)
                for item in test_audit_packaged_src_layout_11709._CONTENT_VERDICTS
            ),
            kind=EnumerationKind.CORPUS,
            why="Cases test_audit_packaged_src_layout_11709 feeds its detector: content verdicts.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_audit_packaged_src_layout_11709._CONTENT_VERDICT_MESSAGES",
            members=tuple(
                str(item)
                for item in test_audit_packaged_src_layout_11709._CONTENT_VERDICT_MESSAGES
            ),
            kind=EnumerationKind.CORPUS,
            why="Cases test_audit_packaged_src_layout_11709 feeds its detector: content verdict messages.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_audit_packaged_src_layout_11709._MULTI_CANDIDATE_PROBES",
            members=tuple(
                str(item)
                for item in test_audit_packaged_src_layout_11709._MULTI_CANDIDATE_PROBES
            ),
            kind=EnumerationKind.CORPUS,
            why="Cases test_audit_packaged_src_layout_11709 feeds its detector: multi candidate probes.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_audit_packaged_src_layout_11709._PROBE_EXIT_MESSAGES",
            members=tuple(
                str(item)
                for item in test_audit_packaged_src_layout_11709._PROBE_EXIT_MESSAGES
            ),
            kind=EnumerationKind.CORPUS,
            why="Cases test_audit_packaged_src_layout_11709 feeds its detector: probe exit messages.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_audit_packaged_src_layout_11709._SINGLE_CANDIDATE_CASES",
            members=tuple(
                str(item)
                for item in test_audit_packaged_src_layout_11709._SINGLE_CANDIDATE_CASES
            ),
            kind=EnumerationKind.CORPUS,
            why="Cases test_audit_packaged_src_layout_11709 feeds its detector: single candidate cases.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_auto_agent_playbook_routing._W1_ROUTING_CASES",
            members=tuple(
                str(item) for item in test_auto_agent_playbook_routing._W1_ROUTING_CASES
            ),
            kind=EnumerationKind.CORPUS,
            why="Cases test_auto_agent_playbook_routing feeds its detector: w1 routing cases.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_events._EVENT_STRING_CASES",
            members=tuple(str(item) for item in test_events._EVENT_STRING_CASES),
            kind=EnumerationKind.CORPUS,
            why="Cases test_events feeds its detector: event string cases.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_gateway_conformance._CASES",
            members=tuple(str(item) for item in test_gateway_conformance._CASES),
            kind=EnumerationKind.CORPUS,
            why="Cases test_gateway_conformance feeds its detector: cases.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_hydraflow_audit_layout._DECLARED_NAME_CASES",
            members=tuple(
                str(item) for item in test_hydraflow_audit_layout._DECLARED_NAME_CASES
            ),
            kind=EnumerationKind.CORPUS,
            why="Cases test_hydraflow_audit_layout feeds its detector: declared name cases.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_issue_11180._FATES",
            members=tuple(str(item) for item in test_issue_11180._FATES),
            kind=EnumerationKind.CORPUS,
            why="Cases test_issue_11180 feeds its detector: fates.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_issue_11481_closing_verb_class.CLOSING_VERBS",
            members=tuple(
                str(item) for item in test_issue_11481_closing_verb_class.CLOSING_VERBS
            ),
            kind=EnumerationKind.CORPUS,
            why="Cases test_issue_11481_closing_verb_class feeds its detector: closing verbs.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_issue_11939_port_fake_name_is_a_hint._SELECTION_CASES",
            members=tuple(
                str(item)
                for item in test_issue_11939_port_fake_name_is_a_hint._SELECTION_CASES
            ),
            kind=EnumerationKind.CORPUS,
            why="Cases test_issue_11939_port_fake_name_is_a_hint feeds its detector: selection cases.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_issue_9566._FALSE_MATCH_CASES",
            members=tuple(str(item) for item in test_issue_9566._FALSE_MATCH_CASES),
            kind=EnumerationKind.CORPUS,
            why="Cases test_issue_9566 feeds its detector: false match cases.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_review_insights._BENIGN_NO_MATCH_CASES",
            members=tuple(
                str(item) for item in test_review_insights._BENIGN_NO_MATCH_CASES
            ),
            kind=EnumerationKind.CORPUS,
            why="Cases test_review_insights feeds its detector: benign no match cases.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_review_insights._DEFICIENCY_MATCH_CASES",
            members=tuple(
                str(item) for item in test_review_insights._DEFICIENCY_MATCH_CASES
            ),
            kind=EnumerationKind.CORPUS,
            why="Cases test_review_insights feeds its detector: deficiency match cases.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_review_insights._NEUTRAL_PRAISE_CORPUS",
            members=tuple(
                str(item) for item in test_review_insights._NEUTRAL_PRAISE_CORPUS
            ),
            kind=EnumerationKind.CORPUS,
            why="Cases test_review_insights feeds its detector: neutral praise corpus.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_term_proposer_evals.EDGE_CASES",
            members=tuple(str(item) for item in test_term_proposer_evals.EDGE_CASES),
            kind=EnumerationKind.CORPUS,
            why="Cases test_term_proposer_evals feeds its detector: edge cases.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_term_proposer_evals.HAPPY_CASES",
            members=tuple(str(item) for item in test_term_proposer_evals.HAPPY_CASES),
            kind=EnumerationKind.CORPUS,
            why="Cases test_term_proposer_evals feeds its detector: happy cases.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_term_proposer_evals.SAD_CASES",
            members=tuple(str(item) for item in test_term_proposer_evals.SAD_CASES),
            kind=EnumerationKind.CORPUS,
            why="Cases test_term_proposer_evals feeds its detector: sad cases.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_triage_honeypot_evals.BENIGN_CASES",
            members=tuple(
                str(item) for item in test_triage_honeypot_evals.BENIGN_CASES
            ),
            kind=EnumerationKind.CORPUS,
            why="Cases test_triage_honeypot_evals feeds its detector: benign cases.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_triage_honeypot_evals.INJECTION_CASES",
            members=tuple(
                str(item) for item in test_triage_honeypot_evals.INJECTION_CASES
            ),
            kind=EnumerationKind.CORPUS,
            why="Cases test_triage_honeypot_evals feeds its detector: injection cases.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_worker_receipts.BUCKETS",
            members=tuple(str(item) for item in test_worker_receipts.BUCKETS),
            kind=EnumerationKind.CORPUS,
            why="Cases test_worker_receipts feeds its detector: buckets.",
            undetected_reason=_CORPUS_IS_EVIDENCE,
        ),
        GuardedEnumeration(
            name="test_issue_12144_llm_seam_fails_closed._lazily_built_llm_clients()",
            members=tuple(
                str(item)
                for item in test_issue_12144_llm_seam_fails_closed._lazily_built_llm_clients()
            ),
            kind=EnumerationKind.CORPUS,
            why=(
                "AST-derived at import: every `self._x = _CLI*(...)` lazy-init "
                "under src/. Floored by the module's own known-positive test."
            ),
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_issue_12144_llm_seam_fails_closed._llm_collaborators_by_loop()",
            members=tuple(
                str(item)
                for item in test_issue_12144_llm_seam_fails_closed._llm_collaborators_by_loop()
            ),
            kind=EnumerationKind.CORPUS,
            why=(
                "AST-derived at import: (loop, attr) for each loop that lazily "
                "builds a real LLM client. Floored by the same known-positive test."
            ),
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="regression_issue_10094._generated_seed_files()",
            members=tuple(
                str(item) for item in regression_issue_10094._generated_seed_files()
            ),
            kind=EnumerationKind.CORPUS,
            why="Discovered at import by regression_issue_10094._generated_seed_files().",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_adversarial_corpus.discover_cases()",
            members=tuple(
                str(item) for item in test_adversarial_corpus.discover_cases()
            ),
            kind=EnumerationKind.CORPUS,
            why="Discovered at import by test_adversarial_corpus.discover_cases().",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_container_images_are_multi_arch._image_workflows()",
            members=tuple(
                str(item)
                for item in test_container_images_are_multi_arch._image_workflows()
            ),
            kind=EnumerationKind.CORPUS,
            why="Discovered at import by test_container_images_are_multi_arch._image_workflows().",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_corpus._entries()",
            members=tuple(str(item) for item in test_corpus._entries()),
            kind=EnumerationKind.CORPUS,
            why="Discovered at import by test_corpus._entries().",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_fake_llm_contract._list_streams()",
            members=tuple(str(item) for item in test_fake_llm_contract._list_streams()),
            kind=EnumerationKind.CORPUS,
            why="Discovered at import by test_fake_llm_contract._list_streams().",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_issue_10440._adr_files()",
            members=tuple(str(item) for item in test_issue_10440._adr_files()),
            kind=EnumerationKind.CORPUS,
            why="Discovered at import by test_issue_10440._adr_files().",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_issue_10870._render_prompt_stems()",
            members=tuple(
                str(item) for item in test_issue_10870._render_prompt_stems()
            ),
            kind=EnumerationKind.CORPUS,
            why="Discovered at import by test_issue_10870._render_prompt_stems().",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_loops_smoke._all_loop_fields()",
            members=tuple(str(item) for item in test_loops_smoke._all_loop_fields()),
            kind=EnumerationKind.CORPUS,
            why="Discovered at import by test_loops_smoke._all_loop_fields().",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_no_screenshot_regression_tests._candidate_files()",
            members=tuple(
                str(item)
                for item in test_no_screenshot_regression_tests._candidate_files()
            ),
            kind=EnumerationKind.CORPUS,
            why="Discovered at import by test_no_screenshot_regression_tests._candidate_files().",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_sandbox_scenario_contract._scenario_module_names()",
            members=tuple(
                str(item)
                for item in test_sandbox_scenario_contract._scenario_module_names()
            ),
            kind=EnumerationKind.CORPUS,
            why="Discovered at import by test_sandbox_scenario_contract._scenario_module_names().",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_cassette_surface_parity._FAKES",
            members=tuple(str(item) for item in test_cassette_surface_parity._FAKES),
            kind=EnumerationKind.CORPUS,
            why="Computed at import by test_cassette_surface_parity, not typed out.",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_claude_hook_shell_tests._HOOK_TESTS",
            members=tuple(
                str(item) for item in test_claude_hook_shell_tests._HOOK_TESTS
            ),
            kind=EnumerationKind.CORPUS,
            why="Computed at import by test_claude_hook_shell_tests, not typed out.",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_issue_11669_self_mod_veto_follows_package.PACKAGE_MEMBERS",
            members=tuple(
                str(item)
                for item in test_issue_11669_self_mod_veto_follows_package.PACKAGE_MEMBERS
            ),
            kind=EnumerationKind.CORPUS,
            why="Computed at import by test_issue_11669_self_mod_veto_follows_package, not typed out.",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_issue_11803_one_flow_stopped.PHASE_MODULES",
            members=tuple(
                str(item) for item in test_issue_11803_one_flow_stopped.PHASE_MODULES
            ),
            kind=EnumerationKind.CORPUS,
            why="Computed at import by test_issue_11803_one_flow_stopped, not typed out.",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_issue_11891_fields_reach_their_producer._GUARDED_SUMMARY_FIELDS",
            members=tuple(
                str(item)
                for item in test_issue_11891_fields_reach_their_producer._GUARDED_SUMMARY_FIELDS
            ),
            kind=EnumerationKind.CORPUS,
            why="Computed at import by test_issue_11891_fields_reach_their_producer, not typed out.",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_issue_11891_fields_reach_their_producer._GUARDED_TRACE_FIELDS",
            members=tuple(
                str(item)
                for item in test_issue_11891_fields_reach_their_producer._GUARDED_TRACE_FIELDS
            ),
            kind=EnumerationKind.CORPUS,
            why="Computed at import by test_issue_11891_fields_reach_their_producer, not typed out.",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_loop_health._INJECT_NAMES",
            members=tuple(str(item) for item in test_loop_health._INJECT_NAMES),
            kind=EnumerationKind.CORPUS,
            why="Computed at import by test_loop_health, not typed out.",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_loop_health._TICK_NAMES",
            members=tuple(str(item) for item in test_loop_health._TICK_NAMES),
            kind=EnumerationKind.CORPUS,
            why="Computed at import by test_loop_health, not typed out.",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_no_shadow_imports._FIXED_PATHS",
            members=tuple(str(item) for item in test_no_shadow_imports._FIXED_PATHS),
            kind=EnumerationKind.CORPUS,
            why="Computed at import by test_no_shadow_imports, not typed out.",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_provider_dial_parity_baseline._DIALS",
            members=tuple(
                str(item) for item in test_provider_dial_parity_baseline._DIALS
            ),
            kind=EnumerationKind.CORPUS,
            why="Computed at import by test_provider_dial_parity_baseline, not typed out.",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_sandbox_parity._IN_PROCESS_SCENARIOS",
            members=tuple(
                str(item) for item in test_sandbox_parity._IN_PROCESS_SCENARIOS
            ),
            kind=EnumerationKind.CORPUS,
            why="Computed at import by test_sandbox_parity, not typed out.",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_scenarios._SCENARIOS",
            members=tuple(str(item) for item in test_scenarios._SCENARIOS),
            kind=EnumerationKind.CORPUS,
            why="Computed at import by test_scenarios, not typed out.",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_issue_11969_mirror_pins_are_real._mirrors()",
            members=tuple(
                str(item)
                for item in test_issue_11969_mirror_pins_are_real._mirrors()  # noqa: SLF001
            ),
            kind=EnumerationKind.CORPUS,
            why="Mirror files discovered on disk by frontmatter shape.",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_provider_dial_source_map._UNRESOLVED_KEYS",
            members=tuple(dial_sources._UNRESOLVED_KEYS),  # noqa: SLF001
            kind=EnumerationKind.CORPUS,
            why="Spawn sites swept from the tree whose principal is not literal.",
            undetected_reason=_DERIVED_CANNOT_GO_STALE,
        ),
        GuardedEnumeration(
            name="test_mockworld_loop_scenario_ratchet.LOOP_CLASS_NAMES",
            members=mockworld.LOOP_CLASS_NAMES,
            kind=EnumerationKind.SUBJECT,
            detects_drop=lambda member: member in loop_builder_classes,
            why=(
                "docs/standards/testing/README.md requires a MockWorld "
                "scenario per load-bearing feature and, until this ratchet, "
                "nothing enforced it. Every loop in this tuple is asked "
                "whether a scenario actually drives it; a dropped member "
                "stops being asked, and the loop keeps sitting in src/ "
                "looking covered. The drop is caught against the hand-written "
                "catalog builders, which name the same 64 classes from a "
                "different, independently maintained object."
            ),
        ),
        GuardedEnumeration(
            name="test_shell_spawn_lint_rules._RULES",
            members=tuple(rule for rule, _spawn in shell_lint._RULES),  # noqa: SLF001
            kind=EnumerationKind.SUBJECT,
            detects_drop=lambda member: member in selected_shell_rules,
            why=(
                "#11724 closed `os.system` on the decision path; S605/S606 close "
                "it repo-wide. Each row pairs a rule with a source line that must "
                "flag, so a dropped row stops anyone ever watching that rule fire "
                "— and the rule stays in `select` looking enforced. Pinned "
                "against the S-rules pyproject actually selects, both directions."
            ),
        ),
        GuardedEnumeration(
            name="test_import_boundary_gate.declarations()",
            members=tuple(row.name for row in boundaries.BOUNDARIES),
            kind=EnumerationKind.SUBJECT,
            detects_drop=_boundary_drop_is_caught,
            why=(
                "#11753. Each row is a whole import rule — ADR-0118's OTel ban, "
                "#10365's container-boot invariant, ADR-0137's no-spawn claim. "
                "Dropping one stops its subject tree being scanned at all while "
                "the driver stays green over the rows that remain, which is the "
                "gate-stops-seeing-its-subject class applied to the gate registry "
                "itself. The drop reddens because every denial the boundary "
                "carried leaves IMPORT_BOUNDARY_FLOOR's live side with it."
            ),
        ),
        GuardedEnumeration(
            name="test_import_boundary_gate.denial_cases()",
            members=boundary_denials,
            kind=EnumerationKind.SUBJECT,
            detects_drop=lambda member: import_boundary_denials(
                boundary_denials, member
            ),
            why=(
                "#11753. One denied module, on one boundary. Dropping "
                "'concurrent.futures' restores the exact bug the fix closed — "
                "ProcessPoolExecutor reaching multiprocessing's machinery "
                "through a package the pin no longer names — with the fix still "
                "in the file. A new denial goes in IMPORT_BOUNDARY_FLOOR as "
                "well as in the declaration."
            ),
        ),
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
        GuardedEnumeration(
            name="test_aggregate_gate_trigger_scope.lane_test_paths()",
            members=aggregate_lane.lane_test_paths(),
            kind=EnumerationKind.SUBJECT,
            detects_drop=lambda member: member in makefile_lane,
            why=(
                "#11730. These are the gates whose subject is a whole tree and "
                "whose only correct trigger is therefore no trigger — they run "
                "in the UNGATED `aggregate-ratchets` CI job. A member dropped "
                "from AGGREGATE_GATES leaves the Makefile lane, so the job "
                "stops running it and that gate silently falls back to being "
                "path-triggered: exactly the defect the lane exists to close, "
                "reproduced inside the fix for it."
            ),
        ),
        GuardedEnumeration(
            name="test_kernel_documents_live_in_files.GUARDED",
            members=kernel_docs.GUARDED,
            kind=EnumerationKind.SUBJECT,
            detects_drop=lambda member: (kernel_docs.REPO_ROOT / member).is_file(),
            why=(
                "Every module in src/onboarding/ is asked whether it holds a "
                "stamped document as a string literal. The set is DERIVED by "
                "glob from the package rather than spelled, precisely because "
                "a literal tuple naming the two known writers is a predicate "
                "that silently narrows: add a third materializer and the "
                "guard stops covering it while staying green. That is the "
                "defect the guard itself exists to close, and widening the "
                "subject already caught a third offender (design_ai.py) the "
                "spelled version would have missed. A member can therefore "
                "only 'drop' by the file leaving disk, which the filesystem "
                "corroborates independently."
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
        GuardedEnumeration(
            name="test_standards_rules_are_wired.ALL",
            members=tuple(name for name, _data in rules_wired.ALL),
            kind=EnumerationKind.SUBJECT,
            detects_drop=lambda member: (
                rules_wired.STANDARDS / member / "standard.yaml"
            ).is_file(),
            why=(
                "Every standard is asked whether its normative rules name a "
                "check. A dropped member stops being asked and keeps looking "
                "governed — the shape that let ports-and-loops state 'Must "
                "satisfy the Protocol structurally' in prose with nothing "
                "checking it (#11908). The drop is caught against the "
                "directory tree itself: a member can only leave this tuple by "
                "its standard.yaml ceasing to exist, which "
                "test_standards_registry.test_every_standard_directory_declares_a_standard_yaml "
                "reddens on independently."
            ),
        ),
        GuardedEnumeration(
            name="test_standards_rules_are_wired.WITH_RULES",
            members=tuple(name for name, _data in rules_wired.WITH_RULES),
            kind=EnumerationKind.SUBJECT,
            detects_drop=_standard_declares_rules,
            why=(
                "The wired subset, whose rule citations are checked for "
                "resolution. A dropped member stops having its citations "
                "verified while the standard still advertises them. The drop "
                "is caught by the shrink-only UNWIRED_STANDARDS_BASELINE in "
                "the same module: un-wiring a standard raises the unwired "
                "count past its mark."
            ),
        ),
        GuardedEnumeration(
            name="test_producer_probe_gate.PROBES",
            members=tuple(probe.name for probe in probe_gate.PROBES),
            kind=EnumerationKind.SUBJECT,
            detects_drop=_probe_drop_is_caught,
            why=(
                "Each row drives one real producer over a recorded fixture and "
                "requires every field of what it emits to be populated or "
                "explicitly excused. A dropped row stops that producer being "
                "asked, and its model keeps sitting in src/ looking covered — "
                "the #11891 shape, where TraceToolProfile.tool_errors and "
                "SubprocessTrace.turn_count were pinned at the model level by "
                "hand-built tests and never at the producer level, so both "
                "shipped structurally empty for the life of the code."
            ),
        ),
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
            name="test_policy_charter_parity._CASES",
            members=tuple(name for name, _ in charter_parity._CASES),  # noqa: SLF001
            kind=EnumerationKind.CORPUS,
            why=(
                "Drift-report shapes the charter arm must decide the same way "
                "`compute_charter_drift` does."
            ),
            undetected_reason=(
                "Evidence, not subject: each member is one report shape fed to "
                "both derivations. The SUBJECT is `NON_FATAL_FINDING_CLASSES` "
                "— which classes are fatal — and that set is guarded where it "
                "is declared, not here. Dropping a case narrows the proof that "
                "the two agree on that shape, which is a coverage question; "
                "the parity invariant itself is asserted per case rather than "
                "over the list, so a drop cannot silently weaken it into "
                "vacuity."
            ),
        ),
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
        GuardedEnumeration(
            name="test_import_boundary_gate.witness_cases()",
            members=tuple(
                f"{boundary.name}::{witness.name}"
                for boundary, witness in boundaries.witness_cases()
            ),
            kind=EnumerationKind.CORPUS,
            why=(
                "Synthetic sources each paired with the verdict the LIVE "
                "collector must reach on it — the two-directional negative "
                "control every import boundary is required to state (#11753)."
            ),
            undetected_reason=(
                "Evidence, not subject: each member is a source shape fed to "
                "the collector, so dropping one drops the proof that the "
                "collector sees that spelling. The SUBJECTS these rows "
                "exercise — the boundaries and their denials — are floored "
                "separately in IMPORT_BOUNDARY_FLOOR, so a rule losing a "
                "member reddens there rather than here. The driver's own "
                "test_every_boundary_witnesses_both_directions keeps the "
                "corpus from shrinking to one direction, which is the shrink "
                "that would matter."
            ),
        ),
        GuardedEnumeration(
            name="test_director_no_authority._RAW_SPAWNS",
            members=tuple(row[0] for row in director._RAW_SPAWNS),  # noqa: SLF001
            kind=EnumerationKind.CORPUS,
            why=(
                "Synthetic spawn sources, each paired with the NAME of the rule "
                "that must fire on it — the negative control for the three "
                "detectors in that file (#11724)."
            ),
            undetected_reason=(
                "Evidence, not subject. Each member is a source shape written "
                "to a victim file; dropping one drops the proof that a "
                "detector sees that spelling, which is a coverage question. "
                "The SUBJECTS these rows exercise are floored separately — "
                "_OS_SPAWN_EXACT and _OS_SPAWN_PREFIXES in DENY_LIST_FLOORS, "
                "the spawn deny-list in IMPORT_BOUNDARY_FLOOR — so a rule "
                "losing a member reddens there rather than here. Both halves "
                "of the corpus are carried in "
                "one table rather than two, because a row's expected rule is "
                "part of the row: the `os-getattr` row expects NO rule to "
                "fire, and is this corpus's false-positive half."
            ),
        ),
    )
