"""Loader tests for the mode-mismatch runner (#11055) — the documented heuristics."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from mode_mismatch_report import load_traces  # noqa: E402


def _write_events(path: Path, events: list[dict[str, object]]) -> Path:
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n")
    return path


def _write_issues(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(json.dumps(rows))
    return path


def test_loader_assembles_traces_from_both_sources(tmp_path: Path) -> None:
    events = _write_events(
        tmp_path / "events.jsonl",
        [
            {"type": "worker_update", "payload": {"issue": 7}},
            {"type": "hitl_escalation", "payload": {"issue": 7}},
            {"type": "phase_change", "payload": {"issue_number": 8}},
            {"type": "transcript_line", "payload": {"issue": 9}},  # not work
            {"type": "worker_update", "payload": {}},  # no issue key
        ],
    )
    # Corrupt tail lines — invalid JSON and a JSON scalar — must be tolerated.
    with events.open("a", encoding="utf-8") as fh:
        fh.write("not json at all\n")
        fh.write('"a bare json string"\n')
    issues = _write_issues(
        tmp_path / "issues.json",
        [
            {"number": 7, "state": "CLOSED", "stateReason": "COMPLETED"},
            {"number": 8, "state": "CLOSED", "stateReason": "NOT_PLANNED"},
            {"number": 9, "state": "OPEN", "stateReason": None},
        ],
    )
    traces, coverage = load_traces(events, issues)
    by_number = {trace.issue_number: trace for trace in traces}

    assert by_number[7].merged and by_number[7].work_started
    assert by_number[7].hitl_escalations == 1
    assert by_number[8].closed_unmerged and by_number[8].work_started
    # transcript lines do not prove the pipeline worked the issue.
    assert not by_number[9].work_started
    assert coverage["issues_in_states_file"] == 3
    assert coverage["issues_seen_working"] == 2


def test_loader_marks_hitl_issue_as_worked(tmp_path: Path) -> None:
    # An escalation implies the pipeline was working the issue even if no
    # other work event survives in the log window.
    events = _write_events(
        tmp_path / "events.jsonl",
        [{"type": "hitl_escalation", "payload": {"issue": 42}}],
    )
    issues = _write_issues(
        tmp_path / "issues.json",
        [{"number": 42, "state": "CLOSED", "stateReason": "COMPLETED"}],
    )
    traces, _ = load_traces(events, issues)
    assert traces[0].work_started
    assert traces[0].hitl_escalations == 1


def test_malformed_rows_never_crash_the_loader(tmp_path: Path) -> None:
    events = _write_events(
        tmp_path / "events.jsonl",
        [{"type": "worker_update", "payload": {"issue": "not-an-int"}}],
    )
    issues = _write_issues(
        tmp_path / "issues.json", [{"number": "seven", "state": "CLOSED"}]
    )
    traces, coverage = load_traces(events, issues)
    assert traces == []
    assert coverage["issues_in_states_file"] == 0
