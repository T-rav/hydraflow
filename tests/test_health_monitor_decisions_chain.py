"""Hash-chaining tests for the health-monitor decision audit trail (CH-1, #9729)."""

from __future__ import annotations

import json
from pathlib import Path

from audit_chain import GENESIS_PREV_HASH, AuditChain


def _record(decision_id: str) -> dict[str, object]:
    return {
        "decision_id": decision_id,
        "timestamp": "2026-07-08T00:00:00+00:00",
        "type": "auto_adjust",
        "parameter": "max_issue_attempts",
        "before": 3,
        "after": 4,
        "reason": "first pass rate low",
        "evidence_summary": "5/10 issues needed retry",
        "outcome_verified": None,
    }


def _read_rows(decisions_dir: Path) -> list[dict[str, object]]:
    text = (decisions_dir / "decisions.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_write_decision_appends_chained_records(tmp_path: Path) -> None:
    from health_monitor_loop import _write_decision

    _write_decision(tmp_path, _record("adj-1"))
    _write_decision(tmp_path, _record("adj-2"))

    rows = _read_rows(tmp_path)
    assert rows[0]["prev_hash"] == GENESIS_PREV_HASH
    assert rows[1]["prev_hash"] == rows[0]["record_hash"]
    assert AuditChain(tmp_path / "decisions.jsonl").verify().ok


def test_update_decision_rechains_and_stays_verifiable(tmp_path: Path) -> None:
    from health_monitor_loop import _update_decision, _write_decision

    _write_decision(tmp_path, _record("adj-1"))
    _write_decision(tmp_path, _record("adj-2"))
    _write_decision(tmp_path, _record("adj-3"))

    _update_decision(tmp_path, "adj-2", {"outcome_verified": "improved"})

    rows = _read_rows(tmp_path)
    assert rows[1]["outcome_verified"] == "improved"
    assert rows[0]["outcome_verified"] is None
    assert AuditChain(tmp_path / "decisions.jsonl").verify().ok


def test_load_decisions_schema_is_unchanged_for_readers(tmp_path: Path) -> None:
    from health_monitor_loop import _load_decisions, _write_decision

    record = _record("adj-1")
    _write_decision(tmp_path, record)
    (loaded,) = _load_decisions(tmp_path)
    for key, value in record.items():
        assert loaded[key] == value


def test_out_of_band_decision_edit_is_detected(tmp_path: Path) -> None:
    from health_monitor_loop import _write_decision

    _write_decision(tmp_path, _record("adj-1"))
    _write_decision(tmp_path, _record("adj-2"))

    rows = _read_rows(tmp_path)
    rows[0]["after"] = 99  # editor-style tamper without re-chaining
    path = tmp_path / "decisions.jsonl"
    path.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows),
        encoding="utf-8",
    )
    assert not AuditChain(path).verify().ok


def test_update_decision_on_unchained_legacy_rows(tmp_path: Path) -> None:
    """Pre-adoption decisions stay amendable without being retrofitted."""
    from health_monitor_loop import _update_decision, _write_decision

    path = tmp_path / "decisions.jsonl"
    legacy = _record("adj-legacy")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")

    _write_decision(tmp_path, _record("adj-new"))
    _update_decision(tmp_path, "adj-legacy", {"outcome_verified": "neutral"})

    rows = _read_rows(tmp_path)
    assert rows[0]["outcome_verified"] == "neutral"
    assert "record_hash" not in rows[0]
    assert AuditChain(path).verify().ok


def test_update_decision_aborts_on_broken_chain(tmp_path: Path) -> None:
    """The sanctioned amendment path must NOT launder corruption: a corrupt
    line present when _update_decision fires would otherwise be silently
    dropped by _load_decisions and re-chained away before RunsGC's verifier
    ever sees it — permanently erasing the tamper evidence."""
    from audit_chain import AuditChain
    from health_monitor_loop import _update_decision, _write_decision

    _write_decision(tmp_path, {"decision_id": "adj-1", "status": "pending"})
    _write_decision(tmp_path, {"decision_id": "adj-2", "status": "pending"})
    decisions = tmp_path / "decisions.jsonl"
    # Corruption/tampering lands between amendments.
    with decisions.open("a", encoding="utf-8") as fh:
        fh.write("NOT JSON — tampered or corrupted\n")
    before = decisions.read_text()

    _update_decision(tmp_path, "adj-1", {"status": "verified"})

    # Amendment aborted: evidence preserved byte-for-byte...
    assert decisions.read_text() == before
    # ...and the verifier still sees the break.
    assert not AuditChain(decisions).verify().ok
