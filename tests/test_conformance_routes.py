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
