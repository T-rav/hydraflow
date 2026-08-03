"""Schema + fidelity tests for the mutant catalog (#10835).

The catalog is data, so these validate its shape (one well-formed mutant per
class, all expected KILLED) and its fidelity (each patch anchor still resolves
against the real tree — catalog rot fails loudly instead of degrading into a
silent no-op that would read as ERRORED at runtime). It does NOT run the real
gates — that is the on-demand ``scripts/mutation_gauntlet.py`` job.
"""

from __future__ import annotations

from pathlib import Path

from mutation_gauntlet import MutantClass, Verdict
from tests.mutation.catalog import CATALOG, load_catalog

REPO = Path(__file__).resolve().parents[2]


def test_catalog_is_non_empty() -> None:
    assert CATALOG


def test_load_catalog_returns_the_catalog() -> None:
    assert load_catalog() == CATALOG


def test_every_mutant_has_a_valid_class() -> None:
    for mutant in CATALOG:
        assert isinstance(mutant.mutant_class, MutantClass)


def test_every_mutant_names_a_target_gate() -> None:
    for mutant in CATALOG:
        assert mutant.target_gate.strip(), mutant.id


def test_every_mutant_patch_is_well_formed() -> None:
    for mutant in CATALOG:
        assert mutant.patch.is_well_formed, mutant.id


def test_every_mutant_expects_killed() -> None:
    # A catalog mutant is a KNOWN fault; a SURVIVOR is a finding, never the
    # authored expectation.
    for mutant in CATALOG:
        assert mutant.expectation is Verdict.KILLED, mutant.id


def test_every_mutant_has_a_substantive_rationale() -> None:
    for mutant in CATALOG:
        assert len(mutant.rationale.strip()) > 30, mutant.id


def test_mutant_ids_are_unique() -> None:
    ids = [mutant.id for mutant in CATALOG]
    assert len(ids) == len(set(ids))


def test_exactly_one_mutant_per_class() -> None:
    classes = [mutant.mutant_class for mutant in CATALOG]

    assert len(classes) == len(set(classes)), "a class is duplicated"
    assert set(classes) == set(MutantClass), "a class is missing"


def test_catalog_anchors_resolve_against_the_real_tree() -> None:
    # Fidelity: each patch must point at a real file whose ``find`` anchor is
    # present. Catches catalog rot when a refactor moves a mutation point.
    for mutant in CATALOG:
        target = REPO / mutant.patch.file
        assert target.is_file(), f"{mutant.id}: missing file {mutant.patch.file}"
        text = target.read_text(encoding="utf-8")
        assert mutant.patch.find in text, (
            f"{mutant.id}: stale anchor — {mutant.patch.find!r} "
            f"no longer present in {mutant.patch.file}"
        )
