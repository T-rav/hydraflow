"""The routing decision chain: append-only, hash-linked, and sanitized."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hydraflow_gateway.routing_audit import (
    GENESIS_HASH,
    AuditChainError,
    RoutingAuditLog,
)

_AT = "2026-08-22T12:00:00+00:00"


def _log(tmp_path: Path) -> RoutingAuditLog:
    return RoutingAuditLog(tmp_path / "routing" / "shadow-decisions.jsonl")


def _append(log: RoutingAuditLog, count: int) -> None:
    for index in range(count):
        log.append({"decision_id": f"dec_{index}"}, recorded_at=_AT)


def test_the_first_record_links_to_the_genesis_hash(tmp_path: Path) -> None:
    """A chain has to start somewhere, and that somewhere is fixed."""
    record = _log(tmp_path).append({"decision_id": "dec_0"}, recorded_at=_AT)

    assert record.prev_hash == GENESIS_HASH


def test_each_record_links_to_the_one_before_it(tmp_path: Path) -> None:
    """The link is what makes a removed row detectable."""
    log = _log(tmp_path)
    first = log.append({"decision_id": "dec_0"}, recorded_at=_AT)
    second = log.append({"decision_id": "dec_1"}, recorded_at=_AT)

    assert second.prev_hash == first.record_hash


def test_sequence_numbers_are_contiguous_from_zero(tmp_path: Path) -> None:
    """A gap in the sequence is a missing decision, and must be visible as one."""
    log = _log(tmp_path)
    _append(log, 3)

    assert [record.seq for record in log.read_all()] == [0, 1, 2]


def test_an_untouched_chain_verifies(tmp_path: Path) -> None:
    """The control case, without which the tamper tests prove nothing."""
    log = _log(tmp_path)
    _append(log, 3)

    assert log.verify().ok


def test_verification_counts_every_record_it_walked(tmp_path: Path) -> None:
    """ "Verified" over an empty file would be a vacuous claim."""
    log = _log(tmp_path)
    _append(log, 3)

    assert log.verify().records == 3


def test_an_empty_chain_verifies_as_zero_records(tmp_path: Path) -> None:
    """A host that has recorded nothing has nothing broken."""
    assert _log(tmp_path).verify().records == 0


def test_editing_a_payload_after_the_fact_breaks_verification(tmp_path: Path) -> None:
    """The property the whole chain exists for."""
    log = _log(tmp_path)
    _append(log, 3)
    rows = [json.loads(line) for line in log.path.read_text().splitlines()]
    rows[1]["payload"]["decision_id"] = "dec_tampered"
    log.path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    assert not log.verify().ok


def test_a_broken_chain_names_the_record_it_broke_at(tmp_path: Path) -> None:
    """ "Something is wrong" is not actionable; "record 1" is."""
    log = _log(tmp_path)
    _append(log, 3)
    rows = [json.loads(line) for line in log.path.read_text().splitlines()]
    rows[1]["payload"]["decision_id"] = "dec_tampered"
    log.path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    assert log.verify().broken_at_seq == 1


def test_removing_a_record_breaks_verification(tmp_path: Path) -> None:
    """Deletion is tampering too, and the sequence catches it."""
    log = _log(tmp_path)
    _append(log, 3)
    rows = log.path.read_text().splitlines()
    log.path.write_text("\n".join([rows[0], rows[2]]) + "\n")

    assert not log.verify().ok


def test_a_malformed_line_fails_verification_rather_than_being_skipped(
    tmp_path: Path,
) -> None:
    """Skipping an unreadable row would quietly shorten the history."""
    log = _log(tmp_path)
    _append(log, 2)
    with open(log.path, "a", encoding="utf-8") as handle:
        handle.write("{not json\n")

    assert not log.verify().ok


def test_read_all_raises_on_a_malformed_line(tmp_path: Path) -> None:
    """A reader asking for the history gets an error, never a truncated one."""
    log = _log(tmp_path)
    _append(log, 1)
    with open(log.path, "a", encoding="utf-8") as handle:
        handle.write("{not json\n")

    with pytest.raises(AuditChainError):
        log.read_all()


def test_a_new_process_continues_the_existing_chain(tmp_path: Path) -> None:
    """``prev_hash`` is read from disk, so a restart does not fork the chain."""
    path = tmp_path / "routing" / "shadow-decisions.jsonl"
    first = RoutingAuditLog(path).append({"decision_id": "dec_0"}, recorded_at=_AT)

    second = RoutingAuditLog(path).append({"decision_id": "dec_1"}, recorded_at=_AT)

    assert second.prev_hash == first.record_hash


def test_a_credential_shaped_payload_is_redacted_before_it_is_stored(
    tmp_path: Path,
) -> None:
    """ADR-0085 redaction applies to this durable write path like every other."""
    log = _log(tmp_path)
    log.append({"detail": "sk-ant-" + "a" * 44}, recorded_at=_AT)

    assert "sk-ant-" not in log.path.read_text(encoding="utf-8")


def test_a_redacted_record_still_verifies(tmp_path: Path) -> None:
    """Hashing the scrubbed bytes is what keeps redaction from faking a tamper."""
    log = _log(tmp_path)
    log.append({"detail": "sk-ant-" + "a" * 44}, recorded_at=_AT)

    assert log.verify().ok


def test_a_record_longer_than_the_tail_window_still_links_correctly(
    tmp_path: Path,
) -> None:
    """A bounded seek must not link onto a line it sliced in half."""
    log = _log(tmp_path)
    first = log.append({"detail": "x" * 128_000}, recorded_at=_AT)

    second = log.append({"decision_id": "dec_1"}, recorded_at=_AT)

    assert second.prev_hash == first.record_hash


def test_a_record_longer_than_the_tail_window_leaves_a_verifiable_chain(
    tmp_path: Path,
) -> None:
    """The oversized-record path is exercised end to end, not just at the link."""
    log = _log(tmp_path)
    log.append({"detail": "x" * 128_000}, recorded_at=_AT)
    log.append({"decision_id": "dec_1"}, recorded_at=_AT)

    assert log.verify().ok


def test_the_persisted_record_carries_its_own_schema_version(tmp_path: Path) -> None:
    """A durable format that cannot say which format it is cannot evolve."""
    log = _log(tmp_path)
    log.append({"decision_id": "dec_0"}, recorded_at=_AT)
    row: dict[str, Any] = json.loads(log.path.read_text().splitlines()[0])

    assert row["schema_version"] == 1
