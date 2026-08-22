"""Unit tests for the durable driver boundary journal (ADR-0137 C8, #11535)."""

from __future__ import annotations

import json
from pathlib import Path

from driver_contracts import DriverCheckpoint, DriverPhase
from driver_journal import DriverJournal


def _checkpoint(**overrides: object) -> DriverCheckpoint:
    base: dict[str, object] = {
        "driver_id": "drv-1",
        "epoch": 1,
        "last_committed_phase": DriverPhase.PLAN,
        "committed_stage_label": "hydraflow-plan",
        "capsule_digest": "cap-1",
    }
    base.update(overrides)
    return DriverCheckpoint(**base)  # type: ignore[arg-type]


def test_committed_keys_is_empty_for_an_issue_with_no_journal_entries(
    tmp_path: Path,
) -> None:
    journal = DriverJournal(tmp_path / "journal.jsonl")

    assert journal.committed_keys(11533) == frozenset()


def test_a_persisted_artifact_alone_does_not_appear_in_committed_keys(
    tmp_path: Path,
) -> None:
    # The load-bearing invariant: an artifact write claims no commit, so it
    # must never make committed_keys() over-claim what actually landed.
    journal = DriverJournal(tmp_path / "journal.jsonl")
    journal.persist_artifact(11533, "11533:1:PLAN:0", {"summary": "drafted"})

    assert journal.committed_keys(11533) == frozenset()


def test_an_appended_checkpoint_appears_in_committed_keys(tmp_path: Path) -> None:
    journal = DriverJournal(tmp_path / "journal.jsonl")
    journal.append_checkpoint(11533, "11533:1:PLAN:0", _checkpoint())

    assert "11533:1:PLAN:0" in journal.committed_keys(11533)


def test_last_epoch_is_none_before_any_checkpoint(tmp_path: Path) -> None:
    journal = DriverJournal(tmp_path / "journal.jsonl")

    assert journal.last_epoch(11533) is None


def test_last_epoch_is_the_highest_epoch_any_checkpoint_committed_at(
    tmp_path: Path,
) -> None:
    journal = DriverJournal(tmp_path / "journal.jsonl")
    journal.append_checkpoint(11533, "k1", _checkpoint(epoch=1))
    journal.append_checkpoint(11533, "k2", _checkpoint(epoch=5))

    assert journal.last_epoch(11533) == 5


def test_a_truncated_final_line_is_skipped_rather_than_raising(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    valid_record = {
        "kind": "checkpoint",
        "issue": 11533,
        "key": "11533:1:PLAN:0",
        "checkpoint": _checkpoint().model_dump(mode="json"),
    }
    path.write_text(
        json.dumps(valid_record, sort_keys=True) + "\n" + '{"kind": "checkpoint", "iss',
        encoding="utf-8",
    )
    journal = DriverJournal(path)

    assert journal.committed_keys(11533) == frozenset({"11533:1:PLAN:0"})


def test_a_fresh_journal_instance_sees_keys_written_by_a_previous_instance(
    tmp_path: Path,
) -> None:
    path = tmp_path / "journal.jsonl"
    first = DriverJournal(path)
    first.append_checkpoint(11533, "11533:1:PLAN:0", _checkpoint())

    second = DriverJournal(path)

    assert "11533:1:PLAN:0" in second.committed_keys(11533)


def test_persist_artifact_with_a_non_json_serializable_value_does_not_raise(
    tmp_path: Path,
) -> None:
    path = tmp_path / "journal.jsonl"
    journal = DriverJournal(path)

    journal.persist_artifact(11533, "11533:1:PLAN:0", {"payload": object()})

    assert json.loads(path.read_text(encoding="utf-8").strip())["kind"] == "artifact"
