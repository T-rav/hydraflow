"""``PythonDecisionEngine`` reproduces the ADR-enforcement ratchet, ADR by ADR.

**How these two paths could disagree** — which is the only thing that makes a
parity test worth writing:

* The ratchet answers with **set arithmetic over the whole population**:
  ``offenders = live_debt() - exempted - live_grandfathered()``, where
  ``live_grandfathered() = baseline_snapshot - resolved - exempted``. It never
  looks at one ADR; it subtracts sets.
* The engine answers **per subject, by an ordered ladder**, and it never sees
  the repo. It is handed four primitive facts per ADR
  (``enforcement_class``, ``in_baseline_snapshot``, ``resolved``, ``exempt``),
  serialized to JSONL and parsed back, and must re-derive the grandfathering
  rule itself. The collector deliberately does **not** emit a ``grandfathered``
  boolean — if it did, both sides would be reading one helper's output and the
  parity would be true by construction.

So the two disagree whenever the ladder's precedence is wrong (exempt before
baseline, class before both), whenever the engine's re-derivation of
``snapshot AND NOT resolved`` drifts from ``snapshot - resolved``, whenever the
collector drops or mis-keys a fact, and whenever the scalar union mangles a
value on the way through JSON. Every one of those is a live way to be wrong,
and each is exercised by a mutation in the PR that added this file.

Parity is asserted over **every Accepted ADR**, as a whole-map equality. A
sampled parity test is the shape that passes while diverging on the one ADR
nobody sampled.

The live corpus only reaches two of the four statuses today (every Accepted ADR
is REAL or allow-listed), so the synthetic corpora below drive the same two
paths over tmp repos seeded to produce all four. They use the same collector
and the same ratchet-side helpers, against a repo root that is not this one —
which is only possible because #11749 gave those helpers a ``repo_root``
parameter instead of a module-level ``REPO`` constant.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from adr_conformance import (
    accepted_adrs,
    live_debt,
    live_grandfathered,
    parse_exemptions,
)
from policy.facts import adr_subject, collect_adr_enforcement_facts
from policy.models import DecisionStatus
from policy.python_engine import PythonDecisionEngine
from policy.store import facts_from_jsonl, facts_to_jsonl

REPO = Path(__file__).resolve().parents[2]
OBSERVED_AT = datetime(2026, 8, 28, 9, 30, tzinfo=UTC)


def _ratchet_status_by_subject(repo_root: Path) -> dict[str, DecisionStatus]:
    """The ratchet's own verdict per Accepted ADR, by its own set arithmetic.

    Deliberately written as the subtraction the gate performs
    (``live_debt`` / exemptions / ``live_grandfathered``) rather than as a
    per-ADR ladder, so this is a genuinely different computation from the
    engine's.
    """
    debt = live_debt(repo_root)
    exempted = set(parse_exemptions(repo_root))
    grandfathered = set(live_grandfathered(repo_root))
    compliant = {n for n in _accepted_numbers(repo_root) if n not in debt}

    status: dict[str, DecisionStatus] = {}
    for number in compliant:
        status[adr_subject(number)] = DecisionStatus.COMPLIANT
    for number in debt & exempted:
        status[adr_subject(number)] = DecisionStatus.EXEMPT
    for number in (debt - exempted) & grandfathered:
        status[adr_subject(number)] = DecisionStatus.GRANDFATHERED
    for number in debt - exempted - grandfathered:
        status[adr_subject(number)] = DecisionStatus.VIOLATED
    return status


def _accepted_numbers(repo_root: Path) -> set[int]:
    return {a.number for a in accepted_adrs(repo_root)}


def _engine_status_by_subject(repo_root: Path) -> dict[str, DecisionStatus]:
    """The engine's verdict, reached only through recorded, serialized facts.

    The JSONL round-trip is not decoration: the epic's claim is that a decision
    is reproducible offline from ``facts.jsonl``, so the parity target is the
    decision made from the *written* evidence, not from live objects.
    """
    facts = collect_adr_enforcement_facts(repo_root, observed_at=OBSERVED_AT)
    replayed = facts_from_jsonl(facts_to_jsonl(facts))
    return {
        decision.subject: decision.status
        for decision in PythonDecisionEngine().decide(replayed)
    }


def _blocking_subjects(repo_root: Path) -> set[str]:
    facts = collect_adr_enforcement_facts(repo_root, observed_at=OBSERVED_AT)
    replayed = facts_from_jsonl(facts_to_jsonl(facts))
    return {
        decision.subject
        for decision in PythonDecisionEngine().decide(replayed)
        if decision.blocking
    }


# ---------------------------------------------------------------------------
# Live corpus — every Accepted ADR, no sampling
# ---------------------------------------------------------------------------


def test_engine_reproduces_the_ratchet_verdict_for_every_accepted_adr() -> None:
    ratchet = _ratchet_status_by_subject(REPO)

    engine = _engine_status_by_subject(REPO)

    assert engine == ratchet, (
        "PythonDecisionEngine diverged from the ADR-enforcement ratchet. "
        "Differences: "
        + json.dumps(
            {
                subject: {
                    "ratchet": ratchet.get(subject, "<absent>"),
                    "engine": engine.get(subject, "<absent>"),
                }
                for subject in sorted(set(ratchet) | set(engine))
                if ratchet.get(subject) != engine.get(subject)
            },
            indent=2,
        )
    )


def test_engine_blocking_set_equals_the_ratchets_offender_set() -> None:
    """``test_no_new_or_ungrandfathered_debt``'s offenders, reached from facts."""
    offenders = {
        adr_subject(n)
        for n in live_debt(REPO)
        - set(parse_exemptions(REPO))
        - live_grandfathered(REPO)
    }

    assert _blocking_subjects(REPO) == offenders


def test_parity_covers_the_whole_accepted_population_not_a_sample() -> None:
    """Anti-vacuity: the map compared above spans every Accepted ADR, and the
    corpus is large enough that agreeing on an empty set is not the reason."""
    accepted = _accepted_numbers(REPO)

    engine = _engine_status_by_subject(REPO)

    assert len(accepted) > 50, f"ADR corpus unexpectedly small: {len(accepted)}"
    assert set(engine) == {adr_subject(n) for n in accepted}


def test_live_corpus_parity_is_not_agreeing_over_one_status() -> None:
    """The live corpus must exercise more than one arm of the ladder, or the
    all-ADR comparison above proves only that both sides say the same word."""
    statuses = set(_engine_status_by_subject(REPO).values())

    assert len(statuses) >= 2, f"live corpus reached only {statuses}"


# ---------------------------------------------------------------------------
# Synthetic corpora — the arms the live repo does not reach
# ---------------------------------------------------------------------------


def _write_adr(
    adr_dir: Path, number: int, *, enforcement: str, enforced_by: str | None
) -> None:
    lines = [
        f"# ADR-{number:04d}: Fixture {number}",
        "",
        "**Status:** Accepted",
        "**Date:** 2026-01-01",
        f"**Enforcement:** {enforcement}",
    ]
    if enforced_by is not None:
        lines.append(f"**Enforced by:** {enforced_by}")
    lines.extend(["", "## Context", "", "Fixture body.", ""])
    (adr_dir / f"{number:04d}-fixture-{number}.md").write_text("\n".join(lines))


def _seed_repo(
    tmp_path: Path, *, snapshot: list[int], resolved: list[int], exemptions: list[int]
) -> Path:
    """A repo whose Accepted ADRs span REAL / WEAK / MISSING and all four lanes."""
    root = tmp_path / "repo"
    adr_dir = root / "docs" / "adr"
    adr_dir.mkdir(parents=True)

    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_real.py").write_text(
        "def test_real() -> None:\n    assert True\n"
    )

    # 0100 REAL — resolving, non-mutating, asserting pytest node.
    _write_adr(
        adr_dir,
        100,
        enforcement="enforced",
        enforced_by="pytest:tests/test_real.py::test_real",
    )
    # 0200 WEAK — enforced but the cited node does not exist.
    _write_adr(
        adr_dir,
        200,
        enforcement="enforced",
        enforced_by="pytest:tests/test_ghost.py::test_ghost",
    )
    # 0300 MISSING — decision-of-record with no Enforced by at all.
    _write_adr(adr_dir, 300, enforcement="decision-of-record", enforced_by=None)
    # 0400 WEAK — manual prose pointer.
    _write_adr(
        adr_dir, 400, enforcement="manual", enforced_by="prose:reviewer checklist"
    )

    baseline_dir = root / "tests" / "architecture"
    baseline_dir.mkdir(parents=True)
    (baseline_dir / "adr_enforcement_baseline.json").write_text(
        json.dumps({"baseline_snapshot": snapshot, "resolved": resolved})
    )

    standards_dir = root / "docs" / "standards" / "adr_enforcement"
    standards_dir.mkdir(parents=True)
    body = ["# Exemptions", "", "## Active exemptions", ""]
    body += [f"- ADR-{n:04d}: fixture justification" for n in exemptions]
    (standards_dir / "exemptions.md").write_text("\n".join(body) + "\n")
    return root


def test_synthetic_corpus_parity_reaches_all_four_statuses(tmp_path: Path) -> None:
    root = _seed_repo(tmp_path, snapshot=[200, 300], resolved=[], exemptions=[400])

    engine = _engine_status_by_subject(root)

    assert engine == {
        "ADR-0100": DecisionStatus.COMPLIANT,
        "ADR-0200": DecisionStatus.GRANDFATHERED,
        "ADR-0300": DecisionStatus.GRANDFATHERED,
        "ADR-0400": DecisionStatus.EXEMPT,
    }
    assert engine == _ratchet_status_by_subject(root)


def test_synthetic_corpus_parity_on_ungrandfathered_debt(tmp_path: Path) -> None:
    """Nothing grandfathered, nothing exempt: both debt ADRs must block."""
    root = _seed_repo(tmp_path, snapshot=[], resolved=[], exemptions=[])

    engine = _engine_status_by_subject(root)

    assert engine == _ratchet_status_by_subject(root)
    assert engine["ADR-0200"] is DecisionStatus.VIOLATED
    assert engine["ADR-0400"] is DecisionStatus.VIOLATED
    assert _blocking_subjects(root) == {"ADR-0200", "ADR-0300", "ADR-0400"}


def test_synthetic_corpus_parity_when_a_baseline_debt_is_marked_resolved(
    tmp_path: Path,
) -> None:
    """A snapshot ADR listed as ``resolved`` leaves the grandfathered set; if it
    is still WEAK the ratchet and the engine must BOTH call it violated."""
    root = _seed_repo(tmp_path, snapshot=[200, 300], resolved=[200], exemptions=[])

    engine = _engine_status_by_subject(root)

    assert engine == _ratchet_status_by_subject(root)
    assert engine["ADR-0200"] is DecisionStatus.VIOLATED
    assert engine["ADR-0300"] is DecisionStatus.GRANDFATHERED


def test_synthetic_corpus_parity_when_an_adr_is_in_both_lanes(
    tmp_path: Path,
) -> None:
    """Exempt wins over grandfathered, on both sides."""
    root = _seed_repo(tmp_path, snapshot=[200], resolved=[], exemptions=[200])

    engine = _engine_status_by_subject(root)

    assert engine == _ratchet_status_by_subject(root)
    assert engine["ADR-0200"] is DecisionStatus.EXEMPT
