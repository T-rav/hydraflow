"""Serialization contract for ``Fact`` / ``StandardDecision`` (#11749).

Every round-trip here is over a **populated** instance and asserts on the
*values and their types*, not on ``loads(dumps(x)) == x``. That identity is
true of an empty dataclass, so a test built on it alone passes while the model
carries nothing — the vacuity this file is written against. In particular the
scalar union is checked type-by-type: ``True`` must come back as ``bool`` and
not as ``1``, which is the one coercion a ``bool | int`` union really can get
wrong (``bool`` is an ``int`` subclass).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from adr_conformance_remediation import RemediationAction
from policy.models import Charter, DecisionStatus, Fact, StandardDecision
from policy.store import (
    FACTS_FILENAME,
    append_facts,
    facts_from_jsonl,
    facts_path,
    facts_to_jsonl,
    read_facts,
)

OBSERVED_AT = datetime(2026, 8, 28, 9, 30, tzinfo=UTC)


def _fact(key: str, value: bool | int | float | str) -> Fact:
    return Fact(
        standard="adr_enforcement",
        subject="ADR-0091",
        key=key,
        value=value,
        observed_at=OBSERVED_AT,
        source="policy.facts.collect_adr_enforcement_facts",
    )


def _populated_decision() -> StandardDecision:
    return StandardDecision(
        standard="adr_enforcement",
        subject="ADR-0091",
        status=DecisionStatus.VIOLATED,
        blocking=True,
        reason="MISSING enforcement debt that is neither grandfathered nor exempt",
        remediation=RemediationAction.FILE_ISSUE,
        facts=[_fact("enforcement_class", "MISSING"), _fact("exempt", False)],
    )


# ---------------------------------------------------------------------------
# Fact — JSON round-trip, values and types
# ---------------------------------------------------------------------------


def test_fact_json_round_trip_preserves_every_field_value() -> None:
    fact = _fact("enforcement_class", "MISSING")

    restored = Fact.model_validate_json(fact.model_dump_json())

    assert restored.standard == "adr_enforcement"
    assert restored.subject == "ADR-0091"
    assert restored.key == "enforcement_class"
    assert restored.value == "MISSING"
    assert restored.observed_at == OBSERVED_AT
    assert restored.source == "policy.facts.collect_adr_enforcement_facts"


def test_fact_json_round_trip_preserves_scalar_types_across_the_union() -> None:
    """``True`` must not come back as ``1``, nor ``1`` as ``1.0``."""
    cases: dict[str, bool | int | float | str] = {
        "exempt": True,
        "resolved": False,
        "attempts": 3,
        "ratio": 0.5,
        "enforcement_class": "WEAK",
    }

    restored = {
        key: Fact.model_validate_json(_fact(key, value).model_dump_json()).value
        for key, value in cases.items()
    }

    assert restored == cases
    assert {key: type(value) for key, value in restored.items()} == {
        "exempt": bool,
        "resolved": bool,
        "attempts": int,
        "ratio": float,
        "enforcement_class": str,
    }


def test_fact_serializes_a_snapshot_identity_for_jsonl_compaction() -> None:
    payload = json.loads(_fact("exempt", True).model_dump_json())

    assert payload["fact_key"] == "adr_enforcement|ADR-0091|exempt"


def test_fact_round_trip_ignores_the_computed_identity_on_the_way_back() -> None:
    """The extra serialized key must not break parsing or equality."""
    fact = _fact("exempt", True)

    assert Fact.model_validate(json.loads(fact.model_dump_json())) == fact


# ---------------------------------------------------------------------------
# StandardDecision — JSON round-trip with facts attached
# ---------------------------------------------------------------------------


def test_policy_decision_json_round_trip_preserves_values_and_enums() -> None:
    restored = StandardDecision.model_validate_json(
        _populated_decision().model_dump_json()
    )

    assert restored.standard == "adr_enforcement"
    assert restored.subject == "ADR-0091"
    assert restored.status is DecisionStatus.VIOLATED
    assert restored.blocking is True
    assert restored.remediation is RemediationAction.FILE_ISSUE
    assert restored.reason.startswith("MISSING enforcement debt")


def test_policy_decision_round_trip_preserves_its_attached_evidence() -> None:
    restored = StandardDecision.model_validate_json(
        _populated_decision().model_dump_json()
    )

    assert [(f.key, f.value) for f in restored.facts] == [
        ("enforcement_class", "MISSING"),
        ("exempt", False),
    ]


def test_policy_decision_remediation_may_be_absent() -> None:
    """The field is optional so an engine with no remediation vocabulary for a
    standard can still return a well-formed decision."""
    decision = StandardDecision(
        standard="rails",
        subject="src/foo.py",
        status=DecisionStatus.COMPLIANT,
        blocking=False,
    )

    assert (
        StandardDecision.model_validate_json(decision.model_dump_json()).remediation
        is None
    )


# ---------------------------------------------------------------------------
# JSONL ledger — append / read
# ---------------------------------------------------------------------------


def test_facts_to_and_from_jsonl_round_trips_a_populated_sequence() -> None:
    facts = [_fact("enforcement_class", "WEAK"), _fact("attempts", 2)]

    text = facts_to_jsonl(facts)

    assert len(text.splitlines()) == 2
    assert facts_from_jsonl(text) == facts


def test_append_facts_writes_a_readable_ledger(tmp_path: Path) -> None:
    path = facts_path(tmp_path)
    facts = [_fact("enforcement_class", "WEAK"), _fact("exempt", False)]

    append_facts(path, facts)

    assert path.name == FACTS_FILENAME
    assert read_facts(path) == facts


def test_append_facts_keeps_one_row_per_fact_identity(tmp_path: Path) -> None:
    """Snapshot semantics: a re-observation replaces, it does not accumulate."""
    path = facts_path(tmp_path)
    append_facts(path, [_fact("enforcement_class", "WEAK")])

    later = Fact(
        standard="adr_enforcement",
        subject="ADR-0091",
        key="enforcement_class",
        value="REAL",
        observed_at=datetime(2026, 8, 29, 9, 30, tzinfo=UTC),
        source="policy.facts.collect_adr_enforcement_facts",
    )
    append_facts(path, [later])

    assert read_facts(path) == [later]


def test_append_facts_is_a_no_op_for_an_empty_sequence(tmp_path: Path) -> None:
    """Appending nothing must leave the ledger byte-identical.

    Asserted against a row an older writer could have left without the
    ``fact_key`` compaction reads, because that is the only shape where the
    early return is observable: falling through to the rewrite would drop the
    row, and a test over well-formed rows alone would pass either way.
    """
    path = facts_path(tmp_path)
    append_facts(path, [_fact("enforcement_class", "WEAK")])
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"legacy_row": true}\n')
    before = path.read_bytes()

    append_facts(path, [])

    assert path.read_bytes() == before


def test_read_facts_returns_empty_for_a_ledger_that_does_not_exist(
    tmp_path: Path,
) -> None:
    assert read_facts(facts_path(tmp_path)) == []


def test_read_facts_skips_a_torn_tail_line(tmp_path: Path) -> None:
    path = facts_path(tmp_path)
    append_facts(path, [_fact("enforcement_class", "WEAK")])
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"standard": "adr_enf')

    assert [f.key for f in read_facts(path)] == ["enforcement_class"]


def test_read_facts_raises_on_a_row_that_is_json_but_not_a_fact(
    tmp_path: Path,
) -> None:
    """A schema break must not be silently dropped — replaying a decision over
    a quietly smaller fact set is how a gate stops firing."""
    path = facts_path(tmp_path)
    append_facts(path, [_fact("enforcement_class", "WEAK")])
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"standard": "adr_enforcement", "subject": "ADR-0091"}\n')

    with pytest.raises(ValueError):
        read_facts(path)


# ---------------------------------------------------------------------------
# Charter
# ---------------------------------------------------------------------------


def test_charter_for_standards_governs_only_what_it_names() -> None:
    charter = Charter.for_standards("adr_conformance")

    assert charter.governs("adr_conformance")
    assert not charter.governs("adr_enforcement")


def test_empty_charter_governs_every_standard() -> None:
    """ "No charter written yet" must not read as "nothing is enforced"."""
    assert Charter().governs("adr_enforcement")
