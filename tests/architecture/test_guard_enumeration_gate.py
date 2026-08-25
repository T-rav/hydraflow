"""Deleting any member of a parametrised guard's subject must redden something.

**Read this before parametrising an architecture guard.** The rule is in
``docs/standards/parametrised_guards/README.md``:

    **Parametrise over the set the guard actually iterates — the literal
    sequence, by reference.** Not a representative of it. Not a predicate that
    selects from it.

Eleven review passes on #11543 produced that rule and could not hold to it:
across passes 6–11 the rate of finding this shape and the rate of fixing it
were equal, and the two instances that survived were introduced by commits
written to close the class. That is a fixed point, not a convergence — it needs
a machine rather than a twelfth reader, and for this needle the machine and the
fix are the same artifact: the sweep below IS the class check.

What it covers, and what each was before it:

- ``DECISION_PATH_MODULES`` — the drops guard derived its subject from
  ``"no spawn" in doc.lower()``, which matched **4 of 10**;
- ``legality`` — one adjacency pinned out of ten, and nine of the other ten
  swaps survived the full suite (**1 of 10**);
- ``ACTUATORS``, ``FORBIDDEN_MUTATIONS``, ``CONVERGENCE_WRITES``,
  ``WRITE_PRIMITIVES``, ``_SPAWN_MACHINERY``, ``_PROPOSAL_KEYS`` — each
  verified by deleting a member and observing no redness anywhere;
- the canary family (#11716) — one rule stated in six places, joining as this
  gate's first consumer rather than as a seventh hand-written copy.

A gate that detects vacuity must not be vacuous, so three of its own failure
modes are pinned here: an empty registry, a subject that resolves to nothing,
and a derivation that has degenerated to matching nothing. This repo has a
documented 100% historical rate of vacuous line-anchored assertions and three
issues closed on tests that never executed their subject; that is the specific
failure this file is designed against.
"""

from __future__ import annotations

import ast
import dataclasses

import pytest

from tests.architecture.guard_enumeration_registry import (
    DENY_LIST_FLOORS,
    EnumerationKind,
    GuardedEnumeration,
    call_witness,
    declared_deny_lists,
    import_witness,
    parametrised_module_sequences,
    proposal_keys_read_by_parser,
    registered_enumerations,
)

ENUMERATIONS: tuple[GuardedEnumeration, ...] = registered_enumerations()

DETECTED: tuple[GuardedEnumeration, ...] = tuple(
    row
    for row in ENUMERATIONS
    if row.kind is EnumerationKind.SUBJECT and row.detects_drop is not None
)

#: Shrink-only ratchet over subjects with no drop-detector. Lower it when you
#: wire one.
#:
#: Raise it for exactly one reason, and say which in the PR: the SCAN started
#: seeing a subject that was already there. A guard newly WRITTEN without a
#: detector is the defect this file exists to catch, re-admitted by exception,
#: and must not move this number.
#:
#: 4 -> 5 (#11723): widening the scan to call-expression argvalues revealed
#: ``test_vitals_conformance_seam.registered_claims()``, which had been
#: parametrised over and unclassified all along. The mark moved because the
#: eyes got better, not because a new guard was let in.
UNDETECTED_SUBJECTS_MAX = 5


def _member_cases() -> list[tuple[GuardedEnumeration, str]]:
    """Every (subject, member) pair, which is the parametrisation itself.

    The test IDs enumerate the members one by one on purpose: the gate's own
    parametrisation has to be over the sets it guards, member by member, or it
    would be the defect it exists to catch.
    """
    return [(row, member) for row in DETECTED for member in row.members]


def _ids(cases: list[tuple[GuardedEnumeration, str]]) -> list[str]:
    return [f"{row.name}::{member}" for row, member in cases]


def check_member(row: GuardedEnumeration, member: str) -> None:
    """Assert that removing *member* from *row* would be caught.

    Factored out so the meta-tests below can run the REAL check against a
    deliberately broken registry row and watch it fail. A property that is only
    ever exercised on the passing case is a property nobody has seen work.
    """
    assert row.detects_drop is not None, row.name
    if member in row.undetected_members:
        assert row.undetected_members[member].strip(), (
            f"{row.name}::{member} is exempt from drop-detection with no "
            "reason, which is indistinguishable from an oversight"
        )
        return
    assert row.detects_drop(member), (
        f"{row.name} would not notice losing {member!r}: the live machinery "
        f"does not derive or witness it, so deleting the entry reddens "
        f"nothing. {row.why}"
    )


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------

_CASES = _member_cases()


@pytest.mark.parametrize(("row", "member"), _CASES, ids=_ids(_CASES))
def test_dropping_a_member_is_detected(row: GuardedEnumeration, member: str) -> None:
    check_member(row, member)


# ---------------------------------------------------------------------------
# The gate's own failure modes
# ---------------------------------------------------------------------------


def assert_sweep_has_a_subject(rows: tuple[GuardedEnumeration, ...]) -> None:
    """Fail closed when there is nothing to sweep.

    Every assertion in this file is over a parametrised set. An empty registry,
    or one whose rows resolve to nothing, makes all of them vacuously true and
    the suite green — the exact way a gate stops seeing its subject while its
    dashboard stays healthy.
    """
    detected = [
        row
        for row in rows
        if row.kind is EnumerationKind.SUBJECT and row.detects_drop is not None
    ]
    if not detected:
        msg = (
            "the enumeration gate has no drop-detected subject; it is asserting nothing"
        )
        raise AssertionError(msg)
    empty = [row.name for row in detected if not row.members]
    if empty:
        msg = f"these subjects resolved to an empty sequence: {sorted(empty)}"
        raise AssertionError(msg)


def test_the_sweep_has_a_subject() -> None:
    assert_sweep_has_a_subject(ENUMERATIONS)


def test_an_empty_registry_fails_the_sweep() -> None:
    """A sweep with no subject must not pass."""
    with pytest.raises(AssertionError, match="asserting nothing"):
        assert_sweep_has_a_subject(())


def test_a_subject_that_resolves_to_nothing_fails_the_sweep() -> None:
    """Resolution HAPPENS — this is not "the literal is present".

    A sibling PR shipped ``test_the_owner_still_owns_it``, which asserted a
    literal appeared in a file and was vacuously satisfiable. Every row's
    ``members`` is read off the live object, and a row that reads back empty
    is a failure rather than a silent zero-case parametrisation.
    """
    # DETECTED[0], not ENUMERATIONS[0]: a corpus row would be filtered out by
    # the sweep and raise "asserting nothing" instead, so the assertion would
    # be measuring the wrong failure and would flip on a registry reorder.
    hollow = dataclasses.replace(DETECTED[0], members=())

    with pytest.raises(AssertionError, match="empty sequence"):
        assert_sweep_has_a_subject((hollow,))


@pytest.mark.parametrize("row", DETECTED, ids=[row.name for row in DETECTED])
def test_a_degenerate_detector_is_a_failure(row: GuardedEnumeration) -> None:
    """A derivation that has stopped matching must fail, not pass quietly.

    ``derived ⊆ literal`` is trivially true when ``derived`` is empty, which is
    how a needle that stops seeing its subject stays green. This runs the real
    check against a detector that has degenerated to matching nothing and
    requires it to report.

    It is also the proof that ``detects_drop`` is **consulted** rather than
    assumed: swapping the callable changes the outcome, so the callable is
    what the gate reads.
    """
    degenerate = dataclasses.replace(
        row, detects_drop=lambda _member: False, undetected_members={}
    )

    with pytest.raises(AssertionError, match="would not notice losing"):
        check_member(degenerate, row.members[0])


#: A member no subject has ever carried. Any detector that answers True for it
#: is answering without looking.
_FABRICATED_MEMBER = "__a_member_that_was_never_in_any_subject__"


#: Shrink-only. Members exempted from drop-detection because a DIFFERENT named
#: mechanism catches them. Lower it when the mechanism is fixed at the source;
#: raise it only for a masking you can name, and name it in the row.
EXEMPT_MEMBERS_MAX = 1


def test_every_member_exemption_names_a_mechanism() -> None:
    exempt = {
        f"{row.name}::{member}": reason
        for row in ENUMERATIONS
        for member, reason in row.undetected_members.items()
    }

    assert not [key for key, reason in exempt.items() if not reason.strip()]
    assert len(exempt) <= EXEMPT_MEMBERS_MAX, (
        f"{len(exempt)} members are exempt from drop-detection "
        f"(ratchet: {EXEMPT_MEMBERS_MAX}): {sorted(exempt)}."
    )


def test_every_exempt_member_is_really_a_member() -> None:
    """An exemption for a member that no longer exists exempts nothing and
    reads as progress — the #11669 class applied to the exemption list."""
    for row in ENUMERATIONS:
        stale = set(row.undetected_members) - set(row.members)
        assert not stale, (
            f"{row.name} exempts members it does not have: {sorted(stale)}"
        )


@pytest.mark.parametrize("row", DETECTED, ids=[row.name for row in DETECTED])
def test_a_detector_rejects_a_member_that_was_never_there(
    row: GuardedEnumeration,
) -> None:
    """The other half of "the detector is consulted".

    ``test_a_degenerate_detector_is_a_failure`` proves the gate reads the
    callable. This proves the callable reads something: a detector that has
    regressed to ``return True`` — the cheapest way to make this whole file
    green — passes every assertion above and fails here.
    """
    assert row.detects_drop is not None
    assert not row.detects_drop(_FABRICATED_MEMBER), (
        f"{row.name}'s detector reports that a member which has never existed "
        "would be caught. It is not consulting its subject, so every drop it "
        "claims to detect is unproven."
    )


def test_every_registered_name_is_unique() -> None:
    names = [row.name for row in ENUMERATIONS]

    assert len(names) == len(set(names)), sorted(
        name for name in names if names.count(name) > 1
    )


def test_every_row_states_what_goes_unguarded() -> None:
    assert not [row.name for row in ENUMERATIONS if not row.why.strip()]


def test_every_undetected_sequence_states_a_reason() -> None:
    """A corpus classification and a missing detector are both exceptions, and
    an exception with no reason is indistinguishable from an oversight."""
    silent = [
        row.name
        for row in ENUMERATIONS
        if row.detects_drop is None and not (row.undetected_reason or "").strip()
    ]

    assert not silent, silent


def test_undetected_subjects_only_shrink() -> None:
    undetected = [
        row.name
        for row in ENUMERATIONS
        if row.kind is EnumerationKind.SUBJECT and row.detects_drop is None
    ]

    assert len(undetected) <= UNDETECTED_SUBJECTS_MAX, (
        f"{len(undetected)} subjects have no drop-detector "
        f"(ratchet: {UNDETECTED_SUBJECTS_MAX}): {sorted(undetected)}. Wire one, "
        "or the guard iterating it can lose a member in silence."
    )


# ---------------------------------------------------------------------------
# The half that stops the registry being "did the author remember"
# ---------------------------------------------------------------------------


#: Sequences the scan is known to see. Not the whole expected set — that would
#: be a second enumeration to maintain — but enough that a scan which has
#: stopped working cannot pass. Two files, two shapes: a plain tuple and an
#: annotated one.
_TRACER_SEQUENCES = frozenset(
    {
        "test_director_no_authority.DECISION_PATH_MODULES",
        "test_director_no_authority.ACTUATORS",
    }
)


def test_the_scan_sees_real_sequences() -> None:
    """Non-vacuity of the scan itself.

    ``test_every_parametrised_arch_sequence_is_classified`` is a containment,
    and a scan that finds nothing satisfies it. A reshape of the AST walk that
    stops matching ``parametrize`` calls has to fail here.
    """
    found = parametrised_module_sequences()

    assert len(found) >= len(_TRACER_SEQUENCES)
    assert {sequence.name for sequence in found} >= _TRACER_SEQUENCES


def test_every_parametrised_arch_sequence_is_classified() -> None:
    """Registration is manual; noticing an unregistered enumeration is not.

    Without this the registry would be exactly the defect one level up — "did
    the author remember to register it" replacing "did the author remember to
    cover all N".
    """
    classified = {row.name for row in ENUMERATIONS}
    scanned = parametrised_module_sequences()
    unclassified = sorted(
        f"{sequence.name} ({sequence.path})"
        for sequence in scanned
        if sequence.name not in classified
    )

    assert not unclassified, (
        "these module-level sequences are fed to @pytest.mark.parametrize under "
        f"tests/architecture/ and are classified nowhere: {unclassified}. "
        "Register them in tests/architecture/guard_enumeration_registry.py as a "
        "SUBJECT with a drop-detector, or as a CORPUS with a reason. See "
        "docs/standards/parametrised_guards/README.md."
    )


# ---------------------------------------------------------------------------
# The derived subjects' other direction
# ---------------------------------------------------------------------------


def test_the_canary_registry_matches_the_brokers_on_disk() -> None:
    """#11716's registry half, in both directions.

    The drop direction is swept above. This is the addition direction: a fourth
    broker that exports ``*_canary_covers`` and never joins ``REGISTERED_PHASES``
    inherits none of the family pins, and copying the prose is what the pattern
    invites.
    """
    from tests.architecture.canary_registry import (
        discovered_canaries,
        registered_canaries,
    )

    discovered = {canary.name for canary in discovered_canaries()}
    registered = {canary.name for canary in registered_canaries()}

    assert discovered, "no src/*_broker.py exports a canary predicate"
    assert discovered == registered, (
        f"unregistered canaries (no conformance sweep): {sorted(discovered - registered)}. "
        f"Registered but gone from src: {sorted(registered - discovered)}."
    )


def test_the_proposal_key_record_matches_the_reads() -> None:
    """``_PROPOSAL_KEYS`` is documented as the written record of what may
    arrive, and it filters nothing — so it drifted in silence both ways.

    Dropping ``"summary"`` reddened nothing, and a new ``raw.get("verdict")``
    would have been recorded nowhere. Deriving the record from the reads makes
    the two inseparable.
    """
    from review_worker_runner import _PROPOSAL_KEYS

    derived = proposal_keys_read_by_parser()

    assert derived, (
        "no literal .get() reads found in parse_review_proposal — the "
        "derivation lost its subject and every containment against it is "
        "vacuously true"
    )
    assert derived == set(_PROPOSAL_KEYS), (
        f"read but unrecorded: {sorted(derived - set(_PROPOSAL_KEYS))}. "
        f"Recorded but never read: {sorted(set(_PROPOSAL_KEYS) - derived)}."
    )


# ---------------------------------------------------------------------------
# The deny-lists, which have a floor instead of a derivation
# ---------------------------------------------------------------------------


def _live_deny_lists() -> dict[str, frozenset[str]]:
    from tests.architecture import test_director_no_authority as director

    return {
        "test_director_no_authority.FORBIDDEN_MUTATIONS": director.FORBIDDEN_MUTATIONS,
        "test_director_no_authority.CONVERGENCE_WRITES": director.CONVERGENCE_WRITES,
        "test_director_no_authority.WRITE_PRIMITIVES": director.WRITE_PRIMITIVES,
        "test_director_no_authority._SPAWN_MACHINERY": director._SPAWN_MACHINERY,  # noqa: SLF001
    }


#: Which real module each deny-list's witness is injected into, and by which
#: extractor. A real subject module rather than a synthetic stub, so what runs
#: is the extractor over the shape it actually meets.
_WITNESS_SUBJECTS: dict[str, tuple[str, str]] = {
    "test_director_no_authority.FORBIDDEN_MUTATIONS": ("src/plan_broker.py", "call"),
    "test_director_no_authority.CONVERGENCE_WRITES": (
        "src/review_worker_runner.py",
        "call",
    ),
    "test_director_no_authority.WRITE_PRIMITIVES": (
        "src/review_worker_runner.py",
        "call",
    ),
    "test_director_no_authority._SPAWN_MACHINERY": ("src/plan_broker.py", "import"),
}


@pytest.mark.parametrize("name", sorted(DENY_LIST_FLOORS))
def test_a_deny_list_only_grows(name: str) -> None:
    """Dropping ``merge_pr`` survived the whole suite (#11723).

    A deny-list has no derivation — most of its members name calls that exist
    nowhere in this repo — so what protects it is a floor: it may gain members
    freely and may not quietly lose one.
    """
    live = _live_deny_lists()[name]
    floor = DENY_LIST_FLOORS[name]

    assert floor, f"{name} has an empty floor; it protects nothing"
    assert floor <= live, (
        f"{name} has stopped denying {sorted(floor - live)}. A name that has "
        "ever been forbidden here cannot silently stop being: the guards over "
        "it look identical either way. Widen the list, or move the floor "
        "deliberately and say why in the PR."
    )


def test_every_registered_deny_list_has_a_floor() -> None:
    """A FIFTH deny-list must not be able to arrive unprotected.

    The three tables here — the floors, the live-list map and the
    witness-subject map — are all hand-written, so comparing them with each
    other proves only that one author typed consistently. The load-bearing
    assertion is the first: the set of deny-lists is DERIVED from the module
    that declares them, so a new one reddens instead of being silently
    unfloored. Without it this test was "did the author remember" one level
    up, which is the defect the registry exists to remove.
    """
    declared = declared_deny_lists()

    assert declared, "no deny-list found in test_director_no_authority"
    assert declared == set(DENY_LIST_FLOORS), (
        f"unfloored deny-lists: {sorted(declared - set(DENY_LIST_FLOORS))}. "
        f"Floored but no longer declared: {sorted(set(DENY_LIST_FLOORS) - declared)}."
    )
    assert set(DENY_LIST_FLOORS) == set(_live_deny_lists())
    assert set(DENY_LIST_FLOORS) == set(_WITNESS_SUBJECTS)


#: A call name no deny-list carries. The negative half of the witness.
_UNDENIED_NAME = "a_call_no_deny_list_has_ever_carried"


@pytest.mark.parametrize("name", sorted(DENY_LIST_FLOORS))
def test_the_deny_list_operand_is_load_bearing(name: str) -> None:
    """The witness must consult the LIST, not just the extractor.

    ``call_witness`` injects a call and asks whether the guard's own
    expression — ``called_names(tree) & <deny list>`` — contains it. Drop the
    ``& <deny list>`` half and it answers True for any identifier, which is
    what an earlier draft of this file did: a fabricated member added to the
    list and its floor stayed green everywhere.

    This is the control that makes that half falsifiable. A name the list does
    not carry must not trip the guard.
    """
    subject, extractor = _WITNESS_SUBJECTS[name]
    live = _live_deny_lists()[name]
    witness = call_witness if extractor == "call" else import_witness

    assert _UNDENIED_NAME not in live
    assert not witness(subject, _UNDENIED_NAME, live), (
        f"{name}'s witness flags {_UNDENIED_NAME!r}, which the list does not "
        "carry. It is reading the extractor and ignoring the set, so every "
        "member it 'sees' is unproven."
    )


def _denied_cases() -> list[tuple[str, str]]:
    return [
        (name, member)
        for name, members in sorted(_live_deny_lists().items())
        for member in sorted(members)
    ]


_DENIED = _denied_cases()


@pytest.mark.parametrize(
    ("name", "member"), _DENIED, ids=[f"{n}::{m}" for n, m in _DENIED]
)
def test_the_guard_can_actually_see_every_denied_name(name: str, member: str) -> None:
    """Every live member is exercised through the guard's own extractor.

    This is what stops the floor rotting into a list of names nothing could
    ever match — the #11669 class applied to call names. It also catches a
    shape mismatch on the way in: ``called_names`` records ``run``, not
    ``subprocess.run``, so a dotted member would sit in the deny-list forever
    catching nothing and this reddens the moment it is added.
    """
    subject, extractor = _WITNESS_SUBJECTS[name]
    live = _live_deny_lists()[name]
    witness = call_witness if extractor == "call" else import_witness

    assert witness(subject, member, live), (
        f"{name} lists {member!r}, but injecting it into {subject} does not "
        "trip the guard: the extractor cannot see that shape, so the entry "
        "forbids nothing."
    )


# ---------------------------------------------------------------------------
# The standard's own anchors
# ---------------------------------------------------------------------------

STANDARD = "docs/standards/parametrised_guards/README.md"


def test_every_test_the_standard_names_exists() -> None:
    """A written anchor pointing at nothing is this standard's own subject.

    The first draft named three: ``test_the_registry_is_not_empty`` (a real
    test, but in a different gate over a different registry),
    ``test_every_subject_resolves_to_a_non_empty_sequence`` (never existed),
    and a ``director_guard`` module that does not exist. A reader following
    them would have concluded the properties were absent.

    Checked mechanically rather than by proofreading, because "the anchor
    still resolves" is exactly the class the repo has already been bitten by
    at eleven path-membership sites and every line-window assertion it had.
    """
    import re

    from tests.architecture.guard_enumeration_registry import repo_root

    root = repo_root()
    text = (root / STANDARD).read_text(encoding="utf-8")
    named = set(re.findall(r"`(test_[a-z0-9_]+)`", text))

    assert named, f"{STANDARD} names no tests; this guard has no subject"

    defined: set[str] = set()
    for path in sorted((root / "tests").rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        defined.update(
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        defined.add(path.stem)

    missing = sorted(named - defined)
    assert not missing, (
        f"{STANDARD} names these tests, and none of them exist: {missing}. "
        "Fix the name or write the test — a standard whose anchors do not "
        "resolve is the defect it documents."
    )
