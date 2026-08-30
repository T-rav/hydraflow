"""The generic driver for every declared import boundary.

Three guards, three hand-rolled AST walks, three mutation-proven bugs — each a
predicate narrower than the vocabulary of the thing it guarded, and each green
either way. This file replaces all three bodies. The rules live as data in
``import_boundary_declarations``; the fidelity lives once in
``import_edge_scan``; what is left here is the part that is the same for every
boundary, so the next one inherits it instead of re-deriving it.

The five properties the declarations promise are enforced HERE, by the runner,
so none of them can be forgotten for the next boundary:

* ``min_subjects`` — :func:`test_the_subject_corpus_did_not_collapse`;
* load-time resolution — :func:`test_a_root_that_matches_nothing_refuses_to_load`
  and :func:`test_an_exclusion_that_names_nothing_refuses_to_load`;
* mandatory two-directional witnesses — :func:`test_a_witness_lands_as_declared`
  and :func:`test_every_boundary_witnesses_both_directions`;
* written exclusion reasons — :func:`test_every_exclusion_states_a_reason`;
* nothing lost — every spelling the three replaced guards caught is a
  ``flagged=True`` witness, run through the live collector.

The decisions currently run through this driver, and where each is written
down: **ADR-0118** (observability belongs to the SRE agent — no OTel under
``src``), **#10365** (the factory container ships ``src`` and not
``scripts``, so no ``src`` module may reach ``scripts`` at boot), and
**ADR-0137** (the director's decision path has no authority — it may not
even import spawn machinery). Adding a fourth means adding a row to
``import_boundary_declarations`` and its denials to
``IMPORT_BOUNDARY_FLOOR``; no code here changes.
"""

from __future__ import annotations

import ast
import dataclasses
from typing import TYPE_CHECKING

import pytest

from tests.architecture.guard_enumeration_registry import IMPORT_BOUNDARY_FLOOR
from tests.architecture.import_boundary_declarations import (
    Denied,
    Exclusion,
    ImportBoundary,
    ImportBoundaryError,
    Scope,
    Witness,
    declarations,
    repo_root,
    sys_path_roots,
)
from tests.architecture.import_edge_scan import (
    denied_edges,
    import_edges,
    package_of,
    resolves_to_module,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pathlib import Path

    from tests.architecture.import_edge_scan import ImportEdge

BOUNDARIES: tuple[ImportBoundary, ...] = declarations()

#: The package a witness source is parsed as. Non-empty on purpose: a witness
#: with a relative import has nothing to resolve against otherwise, and would
#: pass its ``flagged=False`` expectation for the wrong reason.
WITNESS_PACKAGE = "probe_pkg"


def _hits(
    boundary: ImportBoundary, tree: ast.Module, *, package: str
) -> tuple[ImportEdge, ...]:
    """Run the LIVE machinery for *boundary* over *tree*.

    One expression, used by the gate, by the witnesses and by the
    denied-module sweep alike. A witness that ran anything else would be
    checking a copy of the rule rather than the rule.
    """
    return denied_edges(
        import_edges(tree, package=package),
        boundary.denied_modules(),
        boot_only=boundary.scope is Scope.BOOT,
    )


def _describe(boundary: ImportBoundary, path: Path, edge: ImportEdge) -> str:
    root = repo_root()
    shape = (
        "a submodule"
        if resolves_to_module(edge.module, sys_path_roots())
        else "a name in that package"
    )
    return (
        f"{path.relative_to(root)}:{edge.lineno}: {edge.statement} "
        f"[{edge.kind} -> {edge.module}, {shape}]"
    )


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "boundary", declarations(), ids=[row.name for row in BOUNDARIES]
)
def test_no_subject_crosses_the_boundary(boundary: ImportBoundary) -> None:
    """The rule itself, for every declared boundary."""
    roots = sys_path_roots()
    offenders: list[str] = []
    for path in boundary.subjects():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            # A file that will not parse fails in its own suite, but it must
            # not be silently skipped HERE: an unparseable subject is a subject
            # nothing is checking.
            offenders.append(f"{path}: unparseable ({exc})")
            continue
        offenders.extend(
            _describe(boundary, path, edge)
            for edge in _hits(boundary, tree, package=package_of(path, roots))
        )

    assert not offenders, (
        f"{boundary.name}: {boundary.rule}\n\n{boundary.failure}\n\n"
        + "\n  ".join(["Crossings:", *offenders])
    )


@pytest.mark.parametrize(
    "boundary", declarations(), ids=[row.name for row in BOUNDARIES]
)
def test_the_subject_corpus_did_not_collapse(boundary: ImportBoundary) -> None:
    """A gate whose corpus comes back empty reports serenity.

    Checked by the RUNNER, for every declaration, before any verdict above is
    believed — so it is free and cannot be forgotten for the next boundary.
    Four ``make audit`` checks sat inert for years because a deleted file
    produced ``NA`` rather than a failure; a subject glob that stops resolving
    is the same defect with a green tick instead.
    """
    found = len(boundary.subjects())

    assert found >= boundary.min_subjects, (
        f"{boundary.name} resolved {found} subjects, below its floor of "
        f"{boundary.min_subjects}. Its verdict above is therefore over a "
        "corpus that has collapsed, and passing means nothing. Fix the roots "
        f"{list(boundary.roots)} — do not lower the floor to match."
    )


# ---------------------------------------------------------------------------
# Witnesses — the declaration states how it fails, run against the live rule
# ---------------------------------------------------------------------------


def witness_cases() -> tuple[tuple[ImportBoundary, Witness], ...]:
    """Every (boundary, witness) pair. The corpus, member by member."""
    return tuple(
        (boundary, witness) for boundary in BOUNDARIES for witness in boundary.witnesses
    )


_WITNESSES = witness_cases()


@pytest.mark.parametrize(
    ("boundary", "witness"),
    witness_cases(),
    ids=[f"{boundary.name}::{w.name}" for boundary, w in _WITNESSES],
)
def test_a_witness_lands_as_declared(
    boundary: ImportBoundary, witness: Witness
) -> None:
    """The mandatory ``detects_drop``-style field, exercised.

    This is the property that would have caught all three bugs at authoring
    time. The author of the OTel ban would have had to write ``from telemetry
    import spans`` as a must-flag witness, run it, and discover that the
    predicate could not express it. Instead the rule shipped catching the
    spelling nobody writes, and stayed green for as long as nobody wrote the
    other one.

    What runs is :func:`_hits` — the same expression the gate above runs. A
    witness against a re-implementation would be checking the guard's own copy
    of itself, which is the shape ``guard_enumeration_registry`` and
    ``path_membership_registry`` both exist to refuse.
    """
    hits = _hits(
        boundary,
        ast.parse(witness.source, filename=f"<{witness.name}>"),
        package=WITNESS_PACKAGE,
    )

    assert bool(hits) == witness.flagged, (
        f"{boundary.name}::{witness.name} must "
        f"{'be flagged' if witness.flagged else 'NOT be flagged'} and is "
        f"{'flagged' if hits else 'not'}.\n{witness.why}\n"
        f"Source:\n{witness.source}\nEdges seen: {[edge.module for edge in hits]}"
    )


def test_every_boundary_witnesses_both_directions() -> None:
    """A boundary with only positives cannot tell a real predicate from
    ``return True``; one with only negatives cannot tell it from
    ``return False``. Both halves are mandatory, and this is where the
    mandate lives — a dataclass cannot express "non-empty in both
    directions"."""
    thin = {
        boundary.name: (
            sum(1 for w in boundary.witnesses if w.flagged),
            sum(1 for w in boundary.witnesses if not w.flagged),
        )
        for boundary in BOUNDARIES
    }
    missing = sorted(
        f"{name} (flagged={pos}, unflagged={neg})"
        for name, (pos, neg) in thin.items()
        if not pos or not neg
    )

    assert not missing, (
        f"these boundaries do not state how they fail in both directions: "
        f"{missing}. A boundary that has never been watched fire is a boundary "
        "nobody has evidence about."
    )


def test_every_witness_states_why_it_matters() -> None:
    silent = [
        f"{boundary.name}::{witness.name}"
        for boundary in BOUNDARIES
        for witness in boundary.witnesses
        if not witness.why.strip()
    ]

    assert not silent, silent


# ---------------------------------------------------------------------------
# Every denied module is one the live machinery can actually see
# ---------------------------------------------------------------------------


def denial_ids() -> tuple[str, ...]:
    """``<boundary>::<denied module>`` for every denial under enforcement.

    Also the sequence ``IMPORT_BOUNDARY_FLOOR`` is compared against: a boundary
    dropped whole and a single denial dropped from one are the same loss, and
    one floor catches both.
    """
    return tuple(
        f"{boundary.name}::{entry.module}"
        for boundary in BOUNDARIES
        for entry in boundary.denied
    )


def denial_cases() -> tuple[tuple[ImportBoundary, str], ...]:
    """Every (boundary, denied module) pair, which is the parametrisation."""
    return tuple(
        (boundary, entry.module) for boundary in BOUNDARIES for entry in boundary.denied
    )


def check_denial_is_visible(boundary: ImportBoundary, module: str) -> None:
    """Inject *module* into a REAL subject of *boundary* and watch it fire.

    Factored out so the negative control below can run the REAL check against
    a deliberately unreachable denial and watch it fail. A property that is
    only ever exercised on the passing case is a property nobody has seen work.
    """
    subject = boundary.subjects()[0]
    injected = f"{subject.read_text(encoding='utf-8')}\n\nimport {module}\n"

    try:
        tree = ast.parse(injected, filename=str(subject))
    except SyntaxError:
        # A deny-list entry that is not a legal module name — a wildcard, a
        # hyphen, a bare class — cannot appear in any import statement, so it
        # forbids nothing. Reported through the same assertion rather than
        # raised, because "this entry is inert" is the finding, not a crash.
        tree = None
    hits = (
        ()
        if tree is None
        else _hits(boundary, tree, package=package_of(subject, sys_path_roots()))
    )

    assert any(edge.module == module for edge in hits), (
        f"{boundary.name} denies {module!r}, but injecting `import {module}` "
        f"into {subject.relative_to(repo_root())} does not trip the rule. The "
        "collector cannot see that shape, so the entry forbids nothing."
    )


@pytest.mark.parametrize(("boundary", "module"), denial_cases(), ids=list(denial_ids()))
def test_a_denied_module_is_visible_to_the_live_machinery(
    boundary: ImportBoundary, module: str
) -> None:
    """This is what stops a deny-list rotting into names nothing could ever
    match — the #11669 class applied to module names. It also catches a shape
    mismatch on the way in: a deny-list entry the collector cannot express
    would sit there forever forbidding nothing, and this reddens the moment it
    is added."""
    check_denial_is_visible(boundary, module)


def test_every_denied_module_states_a_reason() -> None:
    """A bare module name in a deny-list is indistinguishable from an
    oversight a year later."""
    silent = [
        f"{boundary.name}::{entry.module}"
        for boundary in BOUNDARIES
        for entry in boundary.denied
        if not entry.reason.strip()
    ]

    assert not silent, silent


def test_every_exclusion_states_a_reason() -> None:
    """Exclusions carry written reasons, not bare paths."""
    silent = [
        f"{boundary.name}::{exclusion.path}"
        for boundary in BOUNDARIES
        for exclusion in boundary.exclusions
        if not exclusion.reason.strip()
    ]

    assert not silent, silent


def test_the_denial_floor_and_the_declarations_agree() -> None:
    """The floor is a second copy of the vocabulary, in a second file.

    A deny-list has no derivation — most of these names appear nowhere in this
    repo, which is the point of denying them — so what protects it is a floor,
    and the enforced property is EQUALITY in both directions. Containment
    alone would leave a denial added after the floor was written unprotected
    from arrival: absent from the floor, so dropping it again satisfies
    ``floor <= live`` and reddens nothing.
    """
    live = set(denial_ids())

    assert IMPORT_BOUNDARY_FLOOR, "the denial floor is empty; it protects nothing"
    assert live == IMPORT_BOUNDARY_FLOOR, (
        f"denials that silently stopped being enforced: "
        f"{sorted(IMPORT_BOUNDARY_FLOOR - live)}. Denials with no floor entry, "
        f"unprotected from being dropped again: {sorted(live - IMPORT_BOUNDARY_FLOOR)}. "
        "Adding a denial means adding it to IMPORT_BOUNDARY_FLOOR as well."
    )


# ---------------------------------------------------------------------------
# The driver's own failure modes
# ---------------------------------------------------------------------------


def _probe(**overrides: object) -> ImportBoundary:
    """A copy of a real boundary with one field broken, for the controls below.

    Derived from a live declaration rather than hand-built: a synthetic probe
    that shares nothing with the real ones proves the machinery works on
    synthetic probes.
    """
    return dataclasses.replace(BOUNDARIES[0], **overrides)  # type: ignore[arg-type]


def test_a_root_that_matches_nothing_refuses_to_load() -> None:
    """A missing subject is a hard error, never a skip.

    Four ``make audit`` checks sat inert for years because a deleted file
    produced ``NA``. An arch guard whose glob has stopped matching is the same
    failure wearing a green tick, so it is raised at resolution time.
    """
    with pytest.raises(ImportBoundaryError, match="matches no Python file"):
        _probe(roots=("src/a_directory_that_does_not_exist/**/*.py",)).subjects()


def test_an_exclusion_that_names_nothing_refuses_to_load() -> None:
    """An exclusion for a path that no longer exists exempts nothing and reads
    as caution — the #11669 class applied to the exemption list."""
    stale = Exclusion("src/a_file_that_does_not_exist.py", "stale on purpose")

    with pytest.raises(ImportBoundaryError, match="names nothing on disk"):
        _probe(exclusions=(stale,)).subjects()


def test_a_boundary_that_denies_nothing_refuses_to_load() -> None:
    """A detector with nothing to match must not pass silently: emptying the
    deny-list turns the gate into one that always returns no offenders."""
    from tests.architecture.import_boundary_declarations import (
        _validated,  # noqa: PLC0415
    )

    with pytest.raises(ImportBoundaryError, match="denies nothing"):
        _validated((_probe(denied=()),))


def test_two_boundaries_cannot_share_a_name() -> None:
    """Names key the floor, so a collision would silently merge two rules."""
    from tests.architecture.import_boundary_declarations import (
        _validated,  # noqa: PLC0415
    )

    with pytest.raises(ImportBoundaryError, match="duplicate"):
        _validated((BOUNDARIES[0], BOUNDARIES[0]))


def test_the_subject_floor_can_actually_fail() -> None:
    """The runner's ``min_subjects`` check, run against a collapsed corpus.

    A property only ever exercised on the passing case is a property nobody has
    seen work. This drives the real assertion with a floor the real subject
    count cannot meet and requires it to report.
    """
    unreachable = _probe(min_subjects=10**6)

    with pytest.raises(AssertionError, match="below its floor"):
        test_the_subject_corpus_did_not_collapse(unreachable)


def test_a_witness_that_lands_the_wrong_way_fails() -> None:
    """The witness check is consulted, not assumed.

    Flipping a real witness's expectation must redden. Without this, a witness
    sweep that had degenerated to ``assert True`` would look identical.
    """
    boundary = BOUNDARIES[0]
    flipped = next(w for w in boundary.witnesses if w.flagged)

    with pytest.raises(AssertionError, match="must NOT be flagged"):
        test_a_witness_lands_as_declared(
            boundary, dataclasses.replace(flipped, flagged=False)
        )


def test_a_denial_the_collector_cannot_express_fails() -> None:
    """The visibility sweep is consulted too.

    A deny-list entry that no import statement can name — a wildcard, a
    hyphenated distribution name, a shell glob — forbids nothing. The sweep
    must SAY so rather than quietly finding nothing, and this drives the real
    check with such an entry and requires it to report.
    """
    unreachable = _probe(denied=(Denied("telemetry.*", "not a module name"),))

    with pytest.raises(AssertionError, match="forbids nothing"):
        check_denial_is_visible(unreachable, "telemetry.*")
