from __future__ import annotations

from datetime import UTC, datetime

from adr_conformance import AdrConformance, CheckOutcome, ConformanceKind
from file_util import append_jsonl
from tests.helpers import ConfigFactory


def _metrics_path(config):
    return config.repo_data_root / "metrics" / "adr_conformance.jsonl"


def test_latest_conformance_per_adr(tmp_path) -> None:
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    old = AdrConformance(
        adr_id="0100",
        kind=ConformanceKind.ENFORCED,
        outcome=CheckOutcome.FAIL,
        checks=[],
        timestamp=datetime(2026, 6, 1, tzinfo=UTC),
    )
    new = AdrConformance(
        adr_id="0100",
        kind=ConformanceKind.ENFORCED,
        outcome=CheckOutcome.PASS,
        checks=[],
        timestamp=datetime(2026, 6, 30, tzinfo=UTC),
    )
    other = AdrConformance(
        adr_id="0042",
        kind=ConformanceKind.MANUAL,
        outcome=CheckOutcome.MANUAL,
        checks=[],
        timestamp=datetime(2026, 6, 15, tzinfo=UTC),
    )
    path = _metrics_path(config)
    append_jsonl(path, old.model_dump_json())
    append_jsonl(path, new.model_dump_json())
    append_jsonl(path, other.model_dump_json())

    from dashboard_routes._conformance_routes import latest_conformance_by_adr

    latest = latest_conformance_by_adr(config)
    assert latest["0100"]["outcome"] == "pass"  # newest wins
    assert latest["0042"]["outcome"] == "manual"


def test_latest_conformance_missing_file_returns_empty(tmp_path) -> None:
    config = ConfigFactory.create(repo_root=tmp_path / "repo")

    from dashboard_routes._conformance_routes import latest_conformance_by_adr

    assert latest_conformance_by_adr(config) == {}


def test_latest_conformance_microsecond_boundary_newer_row_wins(tmp_path) -> None:
    """Regression: Pydantic serializes whole-second datetimes as '...56Z' but
    sub-second ones as '...56.000001Z'; lexically '.' < 'Z', so a STRING
    comparison would wrongly keep the whole-second (older) row. Timestamps
    must be compared as parsed datetimes."""
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    older = AdrConformance(
        adr_id="0100",
        kind=ConformanceKind.ENFORCED,
        outcome=CheckOutcome.FAIL,
        checks=[],
        timestamp=datetime(2026, 6, 30, 12, 0, 56, tzinfo=UTC),  # ...56Z
    )
    newer = AdrConformance(
        adr_id="0100",
        kind=ConformanceKind.ENFORCED,
        outcome=CheckOutcome.PASS,
        checks=[],
        timestamp=datetime(2026, 6, 30, 12, 0, 56, 1, tzinfo=UTC),  # ...56.000001Z
    )
    path = _metrics_path(config)
    append_jsonl(path, older.model_dump_json())
    append_jsonl(path, newer.model_dump_json())

    from dashboard_routes._conformance_routes import latest_conformance_by_adr

    latest = latest_conformance_by_adr(config)
    assert latest["0100"]["outcome"] == "pass"  # the truly-newer row


def test_latest_conformance_unparseable_timestamp_treated_as_oldest(tmp_path) -> None:
    """A row with a garbage timestamp must never beat a parseable row (a
    string comparison would rank 'not-a-timestamp' > '2026-...'), and a key
    whose only row has a garbage timestamp is still served, never a crash."""
    import json

    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    valid = AdrConformance(
        adr_id="0100",
        kind=ConformanceKind.ENFORCED,
        outcome=CheckOutcome.PASS,
        checks=[],
        timestamp=datetime(2026, 6, 30, tzinfo=UTC),
    )
    path = _metrics_path(config)
    append_jsonl(path, valid.model_dump_json())
    # Appended AFTER the valid row so string comparison would pick it.
    append_jsonl(
        path,
        json.dumps(
            {"adr_id": "0100", "outcome": "fail", "timestamp": "not-a-timestamp"}
        ),
    )
    append_jsonl(
        path,
        json.dumps(
            {"adr_id": "0042", "outcome": "manual", "timestamp": "not-a-timestamp"}
        ),
    )

    from dashboard_routes._conformance_routes import latest_conformance_by_adr

    latest = latest_conformance_by_adr(config)
    assert latest["0100"]["outcome"] == "pass"  # garbage ts never wins
    assert latest["0042"]["outcome"] == "manual"  # sole garbage-ts row still served


def test_latest_conformance_tolerates_corrupt_line(tmp_path) -> None:
    config = ConfigFactory.create(repo_root=tmp_path / "repo")
    good = AdrConformance(
        adr_id="0100",
        kind=ConformanceKind.ENFORCED,
        outcome=CheckOutcome.PASS,
        checks=[],
        timestamp=datetime(2026, 6, 30, tzinfo=UTC),
    )
    path = _metrics_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write("{not valid json\n")
    append_jsonl(path, good.model_dump_json())

    from dashboard_routes._conformance_routes import latest_conformance_by_adr

    latest = latest_conformance_by_adr(config)
    assert latest["0100"]["outcome"] == "pass"
