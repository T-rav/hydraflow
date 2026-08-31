"""Council conformance must check the verdict VALUE, not just its presence.

`check_council_conformance.py` validated that `**Verdict:**` exists but never
that its value was legal vocabulary for the chamber that wrote it. PR #11870's
first draft shipped `SOUND WITH FIXES` — the PM persona's report register
(SOUND / SOUND WITH FIXES / RESTRUCTURE) — in a design-chamber record whose
contract fixes `SHIP / FIX (list) / RESTRUCTURE`. `make council-conformance`
passed it; a human caught it by eye.

A fitness function blind to the vocabulary it exists to keep honest is the
#11687 defect class one layer up: the checker and the contract are two writers
for one vocabulary, and only one of them was consulted.

Hence the vocabulary is DERIVED from each chamber's own contract line rather
than copied into the checker — a second copy in the script would be the same
two-writers defect, just relocated.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))

import pytest
from check_council_conformance import (
    _base_term,
    chamber_vocabulary,
    verdict_violations,
)

_AGENTS = _ROOT / "agents"


def test_vocabularies_come_from_the_chamber_contracts() -> None:
    """Derived, not hard-coded: editing a chamber's contract moves the gate."""
    assert chamber_vocabulary(_AGENTS, "design") == {"SHIP", "FIX", "RESTRUCTURE"}
    assert chamber_vocabulary(_AGENTS, "arch") == {
        "ACCEPT",
        "ACCEPT WITH FIX",
        "REJECT",
        "SUPERSEDE",
    }


def test_a_chamber_with_no_contract_yields_none_not_an_empty_set() -> None:
    """None means "cannot judge" and skips; an empty set would reject EVERY
    verdict in that chamber. The distinction is the difference between a new
    chamber being ungated and a new chamber being unusable."""
    assert chamber_vocabulary(_AGENTS, "no-such-chamber") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ACCEPT (defer)", "ACCEPT"),
        ("FIX (list)", "FIX"),
        ("  ship  ", "SHIP"),
        ("SOUND WITH FIXES", "SOUND WITH FIXES"),
    ],
)
def test_parenthetical_qualifiers_are_stripped_but_words_are_not(
    raw: str, expected: str
) -> None:
    """`ACCEPT (defer)` is a shipped record and `FIX (list)` is the contract's
    own shape, so the qualifier must not fail. `SOUND WITH FIXES` must survive
    intact — collapsing it to `SOUND` or `FIXES` would accidentally match."""
    assert _base_term(raw) == expected


def _record(tmp_path: Path, chamber: str, verdict: str) -> Path:
    d = tmp_path / "agents" / "council" / "decisions" / chamber
    d.mkdir(parents=True, exist_ok=True)
    rec = d / "0001-x.md"
    rec.write_text(
        f"# {chamber.upper()}-0001: x\n\n"
        f"**Date:** 2026-08-31 · **Seats:** a · **Verdict:** {verdict}\n"
        "**Dissent:** none\n**Enforcement:** decision-of-record\n"
        "**Evidence:** none\n",
        encoding="utf-8",
    )
    return rec


def test_the_pr_11870_defect_is_caught(tmp_path: Path) -> None:
    """The exact escape: a PM-register verdict in a design-chamber record."""
    rec = _record(tmp_path, "design", "SOUND WITH FIXES")
    errors = verdict_violations(tmp_path, _AGENTS, [rec])
    assert len(errors) == 1
    assert "SOUND WITH FIXES" in errors[0]
    assert "design chamber vocabulary" in errors[0]


@pytest.mark.parametrize("verdict", ["SHIP", "FIX (the list)", "RESTRUCTURE"])
def test_legal_design_verdicts_pass(tmp_path: Path, verdict: str) -> None:
    assert (
        verdict_violations(tmp_path, _AGENTS, [_record(tmp_path, "design", verdict)])
        == []
    )


@pytest.mark.parametrize("verdict", ["ACCEPT", "ACCEPT (defer)", "REJECT", "SUPERSEDE"])
def test_legal_arch_verdicts_pass(tmp_path: Path, verdict: str) -> None:
    assert (
        verdict_violations(tmp_path, _AGENTS, [_record(tmp_path, "arch", verdict)])
        == []
    )


def test_a_design_verdict_in_an_arch_record_is_caught(tmp_path: Path) -> None:
    """The chambers' sets are disjoint, so cross-chamber leakage is detectable
    in both directions — not only the one that happened to escape."""
    rec = _record(tmp_path, "arch", "SHIP")
    errors = verdict_violations(tmp_path, _AGENTS, [rec])
    assert len(errors) == 1
    assert "SHIP" in errors[0]


def test_the_real_tree_has_no_violations() -> None:
    """Anti-vacuity + regression floor: the shipped records must pass, so a
    green run means "checked and legal", not "found nothing to check"."""
    records = sorted((_AGENTS / "council" / "decisions").glob("*/[0-9]*.md"))
    assert records, "no decision records found — the sweep would be vacuous"
    assert verdict_violations(_ROOT, _AGENTS, records) == []


def test_collect_errors_actually_calls_the_vocabulary_check(tmp_path: Path) -> None:
    """The WIRING, not the helper.

    Every test above calls `verdict_violations` directly, so deleting its call
    from `collect_errors` leaves them all green while the gate is dead — the
    same vacuity that let the original defect ship. Mutation-checked: removing
    the `errors.extend(verdict_violations(...))` line fails THIS test and only
    this test.

    A full fixture tree is built so `collect_errors` reaches the record: the
    chamber contracts are copied from the real tree, since the vocabulary is
    derived from them.
    """
    import shutil

    from check_council_conformance import collect_errors

    council = tmp_path / "agents" / "council"
    (council / "decisions" / "design").mkdir(parents=True)
    for name in ("design.md", "arch.md", "README.md"):
        shutil.copy(_AGENTS / "council" / name, council / name)
    shutil.copy(
        _AGENTS / "council" / "decisions" / "README.md",
        council / "decisions" / "README.md",
    )

    (council / "decisions" / "design" / "0001-x.md").write_text(
        "# DESIGN-0001: x\n\n"
        "**Date:** 2026-08-31 · **Seats:** a · **Verdict:** SOUND WITH FIXES\n"
        "**Dissent:** none\n**Enforcement:** decision-of-record\n"
        "**Evidence:** none\n",
        encoding="utf-8",
    )

    errors = collect_errors(tmp_path, check_git=False)
    assert any("SOUND WITH FIXES" in e for e in errors), (
        "collect_errors did not surface the illegal verdict — "
        "the vocabulary check is not wired into the gate"
    )
