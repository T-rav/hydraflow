"""Pure read-model tests for the LLM gateway coverage gauge."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from gateway_coverage import (
    build_coverage,
    build_coverage_for_configs,
    gateway_coverage_snapshot_path,
    gateway_ledger_path,
    persist_snapshot,
    read_jsonl_rows,
)
from model_pricing import ModelPricingTable
from prompt_telemetry import PromptTelemetry, prompt_telemetry_source_complete
from tests.helpers import ConfigFactory

_NOW = datetime(2026, 8, 19, 20, tzinfo=UTC)
_SINCE = _NOW - timedelta(hours=24)


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "timestamp": (_NOW - timedelta(hours=1)).isoformat(),
        "request_id": "req-default",
        "source": "gateway",
        "key_id": "key-default",
        "principal": {
            "kind": "spawn",
            "id": "test-runner",
            "spawn_id": "spawn-default",
        },
        "repo_slug": "org-repo",
        "repo_class": "hydraflow",
        "body_capture_policy": "metadata-only",
        "latency_ms": 1.0,
        "status_code": 200,
        "status": "completed",
        "upstream_provider": "anthropic",
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "completed": True,
        "client_aborted": False,
        "observer_malformed_events": 0,
        "cost_usd": 0.0,
        "cost_unknown": False,
        **overrides,
    }
    if row.get("cost_unknown") is True and "cost_usd" not in overrides:
        row["cost_usd"] = None
    return row


def test_complete_coverage_joins_gateway_and_one_shot_spend() -> None:
    snapshot = build_coverage(
        [_row(cost_usd=8.0, request_id="req-1")],
        [
            _row(
                cost_usd=2.0,
                tool="openrouter",
                source="wiki_compilation",
            ),
            _row(cost_usd=50.0, tool="claude", source="implementer"),
        ],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
        scope="repo",
        repo_slug="org/repo",
    )

    assert snapshot.status == "complete"
    assert snapshot.coverage_percent == 13.33
    assert snapshot.gateway_spend_usd == 8.0
    assert snapshot.bypass_spend_usd == 52.0
    assert snapshot.gateway_requests == 1
    assert snapshot.bypass_requests == 2
    assert {row.family for row in snapshot.bypassing_families} == {
        "implementer",
        "wiki_compilation",
    }


def test_direct_contract_recorder_is_visible_as_a_bypass_family() -> None:
    snapshot = build_coverage(
        [],
        [
            _row(
                cost_usd=0.01,
                tool="claude",
                model="sonnet",
                source="contract_refresh",
            )
        ],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
        scope="repo",
        repo_slug="org/repo",
    )

    assert snapshot.coverage_percent == 0.0
    assert snapshot.bypass_requests == 1
    assert snapshot.bypassing_families[0].family == "contract_refresh"


class _UnknownPricing:
    def estimate_cost(self, *args: object, **kwargs: object) -> None:
        return None


class _FixedPricing:
    def estimate_cost(self, *args: object, **kwargs: object) -> float:
        return 1.25


def test_gateway_requested_model_and_canonical_tokens_can_be_repriced() -> None:
    snapshot = build_coverage(
        [
            _row(
                model_requested="priced-model",
                input_tokens=10,
                output_tokens=5,
                cache_read_input_tokens=3,
                cost_unknown=True,
            )
        ],
        [],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
        pricing=cast(ModelPricingTable, _FixedPricing()),
    )

    assert snapshot.status == "complete"
    assert snapshot.gateway_spend_usd == 1.25
    assert snapshot.coverage_percent == 100.0


def test_unpriced_spend_is_partial_and_never_claims_coverage() -> None:
    snapshot = build_coverage(
        [_row(cost_usd=4.0)],
        [
            _row(
                tool="kimi",
                source="term_proposer",
                model="future-model",
                input_tokens=100,
                cost_unknown=True,
            )
        ],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
        repo_slug="org-repo",
        scope="repo",
        pricing=cast(ModelPricingTable, _UnknownPricing()),
    )

    assert snapshot.status == "partial"
    assert snapshot.coverage_percent is None
    assert snapshot.known_spend_coverage_percent == 100.0
    assert snapshot.unpriced_bypass_requests == 1
    assert snapshot.bypassing_families[0].unpriced_calls == 1


def test_explicit_unknown_cost_without_tokens_remains_partial() -> None:
    snapshot = build_coverage(
        [_row(cost_usd=None, cost_unknown=True)],
        [],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
    )

    assert snapshot.status == "partial"
    assert snapshot.coverage_percent is None
    assert snapshot.known_spend_coverage_percent is None
    assert snapshot.unpriced_gateway_requests == 1


def test_null_prompt_telemetry_cost_without_tokens_remains_partial() -> None:
    snapshot = build_coverage(
        [],
        [
            _row(
                tool="openrouter",
                source="wiki_compilation",
                estimated_cost_usd=None,
                cost_usd=None,
                cost_unknown=True,
            )
        ],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
    )

    assert snapshot.status == "partial"
    assert snapshot.unpriced_bypass_requests == 1


def test_no_spend_is_no_data() -> None:
    snapshot = build_coverage(
        [],
        [],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
    )
    assert snapshot.status == "no_data"
    assert snapshot.coverage_percent is None
    assert snapshot.known_spend_coverage_percent is None


def test_window_repo_and_gateway_telemetry_filters_prevent_double_counting() -> None:
    snapshot = build_coverage(
        [
            _row(cost_usd=3.0),
            _row(cost_usd=7.0, repo_slug="other-repo"),
            _row(cost_usd=9.0, timestamp=(_SINCE - timedelta(seconds=1)).isoformat()),
        ],
        [
            _row(cost_usd=1.0, tool="zai", source="adr_reviewer"),
            _row(
                cost_usd=5.0,
                tool="zai",
                source="adr_reviewer",
                gateway_request_id="req-routed",
            ),
            _row(cost_usd=5.0, tool="openrouter", source="gateway_proxy"),
            _row(cost_usd=5.0, tool="kimi", source="other", repo_slug="other"),
        ],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
        scope="repo",
        repo_slug="org-repo",
    )

    assert snapshot.gateway_spend_usd == 3.0
    assert snapshot.bypass_spend_usd == 1.0
    assert snapshot.coverage_percent == 75.0
    assert snapshot.bypass_requests == 1


def test_gateway_ledger_started_at_is_supported_for_backward_compatibility() -> None:
    legacy = _row(cost_usd=3.0, request_id="req-legacy")
    legacy["started_at"] = legacy.pop("timestamp")
    snapshot = build_coverage(
        [legacy],
        [],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
        scope="repo",
        repo_slug="org/repo",
    )

    assert snapshot.gateway_requests == 1
    assert snapshot.gateway_spend_usd == 3.0


def test_naive_timestamp_is_utc_and_invalid_timestamp_is_skipped() -> None:
    snapshot = build_coverage(
        [
            _row(
                timestamp=(_NOW - timedelta(minutes=5))
                .replace(tzinfo=None)
                .isoformat(),
                cost_usd=1.0,
            ),
            _row(timestamp="not-a-timestamp", cost_usd=99.0),
        ],
        [],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
    )

    assert snapshot.gateway_requests == 1
    assert snapshot.status == "partial"
    assert snapshot.coverage_percent is None


def test_unknown_inference_tool_cannot_disappear_from_complete_coverage() -> None:
    snapshot = build_coverage(
        [_row(cost_usd=8.0)],
        [
            _row(
                tool="openroutr",
                source="wiki_compilation",
                estimated_cost_usd=2.0,
            )
        ],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
    )

    assert snapshot.status == "partial"
    assert snapshot.coverage_percent is None
    assert snapshot.gateway_requests == 1
    assert snapshot.bypass_requests == 0


def test_identityless_gateway_fragment_is_not_counted_as_numerator() -> None:
    snapshot = build_coverage(
        [
            {
                "timestamp": (_NOW - timedelta(minutes=5)).isoformat(),
                "cost_usd": 9.0,
            }
        ],
        [],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
    )

    assert snapshot.status == "partial"
    assert snapshot.coverage_percent is None
    assert snapshot.gateway_requests == 0
    assert snapshot.gateway_spend_usd == 0.0


def test_partial_gateway_fragment_cannot_manufacture_complete_coverage() -> None:
    snapshot = build_coverage(
        [
            {
                "source": "gateway",
                "request_id": "fake",
                "repo_slug": "org/repo",
                "timestamp": (_NOW - timedelta(minutes=5)).isoformat(),
                "cost_usd": 2.0,
            }
        ],
        [],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
    )

    assert snapshot.status == "partial"
    assert snapshot.source_data_complete is False
    assert snapshot.coverage_percent is None
    assert snapshot.gateway_requests == 0


def test_gateway_marked_prompt_telemetry_is_a_valid_excluded_duplicate() -> None:
    snapshot = build_coverage(
        [_row(cost_usd=8.0)],
        [
            _row(
                source="implementer",
                tool="gateway",
                estimated_cost_usd=8.0,
            )
        ],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
    )

    assert snapshot.status == "complete"
    assert snapshot.source_data_complete is True
    assert snapshot.coverage_percent == 100.0
    assert snapshot.bypass_requests == 0


def test_jsonl_reader_is_tolerant_and_snapshot_write_is_atomic_shape(
    tmp_path: Path,
) -> None:
    path = tmp_path / "rows.jsonl"
    path.write_text('\n{"cost_usd": 1}\nnot-json\n[]\n{"cost_usd": 2}\n')
    assert [row["cost_usd"] for row in read_jsonl_rows(path)] == [1, 2]
    assert read_jsonl_rows(tmp_path / "missing.jsonl") == []

    repo = tmp_path / "repo"
    repo.mkdir()
    config = ConfigFactory.create(repo_root=repo)
    object.__setattr__(config, "data_root", tmp_path / "data")
    snapshot = build_coverage([], [], since=_SINCE, until=_NOW, window_label="24h")
    written = persist_snapshot(config, snapshot)
    assert written == gateway_coverage_snapshot_path(config)
    assert json.loads(written.read_text())["status"] == "no_data"
    assert (
        gateway_ledger_path(config) == config.data_root / "gateway" / "requests.jsonl"
    )

    object.__setattr__(config, "gateway_ledger_path", "/gateway/requests.jsonl")
    assert gateway_ledger_path(config) == Path("/gateway/requests.jsonl")


def test_jsonl_reader_degrades_when_path_cannot_be_statted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "unreadable.jsonl"

    def deny_stat(*_args: object, **_kwargs: object) -> bool:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "is_file", deny_stat)

    assert read_jsonl_rows(path) == []


@pytest.mark.parametrize("corrupt_source", ["gateway", "inference"])
def test_invalid_utf8_source_never_crashes_or_claims_complete_coverage(
    corrupt_source: str,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = ConfigFactory.create(repo_root=repo)
    object.__setattr__(config, "data_root", tmp_path / "data")
    ledger_path = gateway_ledger_path(config)
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_text(json.dumps(_row(cost_usd=8.0)) + "\n")
    inference_path = config.cost_inferences_path
    inference_path.parent.mkdir(parents=True)
    inference_path.write_text(
        json.dumps(
            _row(
                source="wiki_compilation",
                tool="openrouter",
                estimated_cost_usd=2.0,
            )
        )
        + "\n"
    )
    corrupt_path = ledger_path if corrupt_source == "gateway" else inference_path
    corrupt_path.write_bytes(b"\xff\xfe\n")

    snapshot = build_coverage_for_configs(
        [config],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
        scope="global",
        repo_slug=None,
    )

    assert snapshot.status == "partial"
    assert snapshot.source_data_complete is False
    assert snapshot.coverage_percent is None


def test_unreadable_inference_source_never_reports_complete_coverage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = ConfigFactory.create(repo_root=repo)
    object.__setattr__(config, "data_root", tmp_path / "data")
    ledger_path = gateway_ledger_path(config)
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_text(json.dumps(_row(cost_usd=8.0)) + "\n")
    inference_path = config.cost_inferences_path
    original_is_file = Path.is_file

    def deny_inference_stat(path: Path) -> bool:
        if path == inference_path:
            raise PermissionError("denied")
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", deny_inference_stat)

    snapshot = build_coverage_for_configs(
        [config],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
        scope="global",
        repo_slug=None,
    )

    assert snapshot.status == "partial"
    assert snapshot.coverage_percent is None
    assert snapshot.known_spend_coverage_percent == 100.0
    assert snapshot.gateway_requests == 1


def test_dropped_prompt_telemetry_write_forces_partial_coverage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = ConfigFactory.create(repo_root=repo)
    object.__setattr__(config, "data_root", tmp_path / "data")
    telemetry = PromptTelemetry(config)
    original_append = telemetry._chain.append

    def deny_append(_record: dict[str, object]) -> None:
        raise OSError("disk denied")

    monkeypatch.setattr(telemetry._chain, "append", deny_append)
    telemetry.record(
        source="contract_refresh",
        tool="claude",
        model="sonnet",
        issue_number=None,
        pr_number=None,
        session_id=None,
        prompt_chars=4,
        transcript_chars=4,
        duration_seconds=0.1,
        success=True,
    )
    monkeypatch.setattr(telemetry._chain, "append", original_append)
    telemetry.record(
        source="wiki_compilation",
        tool="openrouter",
        model="openrouter/test",
        issue_number=None,
        pr_number=None,
        session_id=None,
        prompt_chars=4,
        transcript_chars=4,
        duration_seconds=0.1,
        success=True,
    )
    ledger_path = gateway_ledger_path(config)
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_text(json.dumps(_row(cost_usd=8.0)) + "\n")

    snapshot = build_coverage_for_configs(
        [config],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
        scope="global",
        repo_slug=None,
    )

    assert snapshot.status == "partial"
    assert snapshot.coverage_percent is None
    assert snapshot.gateway_requests == 1


def test_tampered_prompt_telemetry_chain_forces_partial_coverage(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = ConfigFactory.create(repo_root=repo)
    object.__setattr__(config, "data_root", tmp_path / "data")
    telemetry = PromptTelemetry(config)
    telemetry.record(
        source="wiki_compilation",
        tool="openrouter",
        model="openrouter/test",
        issue_number=None,
        pr_number=None,
        session_id=None,
        prompt_chars=100,
        transcript_chars=50,
        duration_seconds=0.1,
        success=True,
    )
    inference_path = config.cost_inferences_path
    row = json.loads(inference_path.read_text())
    row["estimated_cost_usd"] = 0.0
    inference_path.write_text(json.dumps(row) + "\n")
    ledger_path = gateway_ledger_path(config)
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_text(json.dumps(_row(cost_usd=8.0)) + "\n")

    snapshot = build_coverage_for_configs(
        [config],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
        scope="global",
        repo_slug=None,
    )

    assert snapshot.status == "partial"
    assert snapshot.coverage_percent is None


def test_prefix_truncated_prompt_telemetry_forces_partial_coverage(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = ConfigFactory.create(repo_root=repo)
    object.__setattr__(config, "data_root", tmp_path / "data")
    telemetry = PromptTelemetry(config)
    telemetry.record(
        source="contract_refresh",
        tool="claude",
        model="sonnet",
        issue_number=None,
        pr_number=None,
        session_id=None,
        prompt_chars=100,
        transcript_chars=50,
        duration_seconds=0.1,
        success=True,
    )
    telemetry.record(
        source="implementer",
        tool="gateway",
        model="sonnet",
        issue_number=None,
        pr_number=None,
        session_id=None,
        prompt_chars=100,
        transcript_chars=50,
        duration_seconds=0.1,
        success=True,
    )
    inference_path = config.cost_inferences_path
    rows = inference_path.read_text().splitlines()
    assert len(rows) == 2
    inference_path.write_text(rows[1] + "\n")
    ledger_path = gateway_ledger_path(config)
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_text(json.dumps(_row(cost_usd=8.0)) + "\n")

    snapshot = build_coverage_for_configs(
        [config],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
        scope="global",
        repo_slug=None,
    )

    assert prompt_telemetry_source_complete(inference_path) is False
    assert snapshot.status == "partial"
    assert snapshot.coverage_percent is None
    assert snapshot.gateway_requests == 1
    assert snapshot.bypass_requests == 0


def test_missing_sources_are_no_data_only_until_activity_is_observed(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = ConfigFactory.create(repo_root=repo)
    object.__setattr__(config, "data_root", tmp_path / "data")

    empty = build_coverage_for_configs(
        [config],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
        scope="global",
        repo_slug=None,
    )
    assert empty.status == "no_data"

    ledger_path = gateway_ledger_path(config)
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_text(json.dumps(_row(cost_usd=8.0)) + "\n")
    partial = build_coverage_for_configs(
        [config],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
        scope="global",
        repo_slug=None,
    )

    assert partial.status == "partial"
    assert partial.coverage_percent is None


def test_gateway_rows_are_priced_with_anthropic_shaped_usage() -> None:
    """Gateway streams are Anthropic-shaped for EVERY upstream — ``input_tokens``
    excludes cache — so the table's one-shot ``input_includes_cache`` flag for
    GLM must not subtract the cache from a gateway row's billable input."""
    snapshot = build_coverage(
        [
            _row(
                upstream_provider="zai-harness",
                model_requested="glm-5.2",
                model_served="glm-5.3",
                input_tokens=5_000_000,
                output_tokens=53_200,
                cache_read_input_tokens=4_678_400,
                usage_complete=True,
                cost_usd=None,
                cost_unknown=True,
            )
        ],
        [],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
    )

    exclusive = (1.4 * 5_000_000 + 4.4 * 53_200 + 0.26 * 4_678_400) / 1_000_000
    assert snapshot.gateway_requests == 1
    assert snapshot.unpriced_gateway_requests == 0
    assert snapshot.gateway_spend_usd == pytest.approx(exclusive, abs=1e-6)


def test_gateway_row_with_incomplete_usage_is_never_repriced() -> None:
    """An aborted stream's partial counts are not a price; the row stays unknown."""
    snapshot = build_coverage(
        [
            _row(
                status="client-aborted",
                status_code=499,
                completed=False,
                client_aborted=True,
                usage_complete=False,
                model_served="glm-5.3",
                input_tokens=1_244,
                cache_read_input_tokens=46_784,
                cost_usd=None,
                cost_unknown=True,
            )
        ],
        [],
        since=_SINCE,
        until=_NOW,
        window_label="24h",
    )

    assert snapshot.gateway_requests == 1
    assert snapshot.unpriced_gateway_requests == 1
    assert snapshot.gateway_spend_usd == 0.0


def test_bypass_rows_are_priced_by_usage_shape_then_tool() -> None:
    """Direct CLI-harness rows (tool=claude, or stamped anthropic) are
    Anthropic-shaped; the model's one-shot flag must not subtract their cache."""
    exclusive = (1.4 * 5_000_000 + 0.26 * 4_000_000) / 1e6
    inclusive = (1.4 * 1_000_000 + 0.26 * 4_000_000) / 1e6
    common = {
        "model": "glm-5.2",
        "input_tokens": 5_000_000,
        "output_tokens": 0,
        "cache_read_input_tokens": 4_000_000,
        "cost_usd": None,
        "cost_unknown": True,
    }

    def spend(**fields: object) -> float:
        snapshot = build_coverage(
            [],
            [_row(source="implementer", **common, **fields)],
            since=_SINCE,
            until=_NOW,
            window_label="24h",
        )
        return snapshot.bypass_spend_usd

    assert spend(tool="zai", usage_shape="anthropic") == pytest.approx(
        exclusive, abs=1e-6
    )
    assert spend(tool="claude") == pytest.approx(exclusive, abs=1e-6)
    assert spend(tool="zai") == pytest.approx(inclusive, abs=1e-6)
