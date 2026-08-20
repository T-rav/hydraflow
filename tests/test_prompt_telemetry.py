"""Tests for prompt_telemetry.py."""

from __future__ import annotations

import json
import threading

import pytest

import prompt_telemetry as prompt_telemetry_module
from model_pricing import ModelPricingTable
from prompt_telemetry import (
    PromptTelemetry,
    _as_float,
    parse_command_tool_model,
    prompt_telemetry_health_path,
    prompt_telemetry_source_complete,
)
from tests.helpers import ConfigFactory


@pytest.fixture
def telemetry(tmp_path):
    config = ConfigFactory.create(repo_root=tmp_path)
    return PromptTelemetry(config)


class TestParseCommandToolModel:
    def test_parses_claude_model(self):
        tool, model = parse_command_tool_model(
            ["claude", "-p", "--model", "opus", "--verbose"]
        )
        assert tool == "claude"
        assert model == "opus"

    def test_parses_codex_model(self):
        tool, model = parse_command_tool_model(
            ["codex", "exec", "--json", "--model", "gpt-5"]
        )
        assert tool == "codex"
        assert model == "gpt-5"

    def test_parses_pi_model(self):
        tool, model = parse_command_tool_model(
            ["pi", "-p", "--mode", "json", "--model", "gpt-5.3-codex"]
        )
        assert tool == "pi"
        assert model == "gpt-5.3-codex"


class TestPromptTelemetry:
    def test_record_writes_inference_file(self, telemetry):
        telemetry.record(
            source="reviewer",
            tool="claude",
            model="sonnet",
            issue_number=42,
            pr_number=101,
            session_id="sess-1",
            prompt_chars=800,
            transcript_chars=400,
            duration_seconds=2.5,
            success=True,
            stats={
                "history_chars_before": 200,
                "history_chars_after": 100,
                "context_chars_before": 1200,
                "context_chars_after": 900,
                "cache_hits": 2,
                "cache_misses": 1,
            },
        )

        inf_file = telemetry._config.cost_inferences_path
        assert inf_file.exists()

        rows = [ln for ln in inf_file.read_text().splitlines() if ln.strip()]
        assert len(rows) == 1
        row = json.loads(rows[0])
        assert row["source"] == "reviewer"
        assert row["pr_number"] == 101
        assert row["session_id"] == "sess-1"
        assert row["history_chars_saved"] == 100
        assert row["context_chars_saved"] == 300
        assert row["cache_hit_rate"] == 0.6667
        assert row["token_source"] == "estimated"
        assert row["total_tokens"] == row["total_est_tokens"]
        assert row["token_estimation_mode"] == "model-aware-chars-per-token"
        assert row["token_estimation_confidence"] in {"low", "medium"}
        marker = json.loads(prompt_telemetry_health_path(inf_file).read_text())
        assert marker["status"] == "healthy"
        assert marker["record_count"] == 1
        assert marker["chain_head"] == row["record_hash"]
        assert prompt_telemetry_source_complete(inf_file) is True

    def test_append_failure_persists_unhealthy_source_marker(
        self, telemetry: PromptTelemetry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def deny_append(_record: dict[str, object]) -> None:
            raise OSError("disk denied")

        monkeypatch.setattr(telemetry._chain, "append", deny_append)

        telemetry.record(
            source="reviewer",
            tool="claude",
            model="sonnet",
            issue_number=None,
            pr_number=None,
            session_id=None,
            prompt_chars=100,
            transcript_chars=10,
            duration_seconds=0.1,
            success=True,
        )

        path = telemetry._config.cost_inferences_path
        marker = json.loads(prompt_telemetry_health_path(path).read_text())
        assert marker["status"] == "degraded"
        assert prompt_telemetry_source_complete(path) is False

    def test_newer_degradation_wins_over_older_healthy_completion(
        self, telemetry: PromptTelemetry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Serialize the state transition and marker write as one operation."""
        healthy_write_started = threading.Event()
        release_healthy_write = threading.Event()
        newer_writer_progressed = threading.Event()
        errors: list[Exception] = []
        real_atomic_write = prompt_telemetry_module.atomic_write

        class ObservableLock:
            def __init__(self) -> None:
                self._lock = threading.Lock()

            def __enter__(self) -> ObservableLock:
                if not self._lock.acquire(blocking=False):
                    newer_writer_progressed.set()
                    self._lock.acquire()
                return self

            def __exit__(
                self,
                exc_type: object,
                exc_value: object,
                traceback: object,
            ) -> None:
                self._lock.release()

        def controlled_atomic_write(path, data: str) -> None:
            thread_name = threading.current_thread().name
            if thread_name == "older-healthy":
                healthy_write_started.set()
                release_healthy_write.wait(timeout=5)
            real_atomic_write(path, data)
            if thread_name == "newer-degraded":
                newer_writer_progressed.set()

        def set_health(status: str) -> None:
            try:
                telemetry._set_source_health(
                    status,
                    chain_head="older-head" if status == "healthy" else None,
                    record_count=1 if status == "healthy" else None,
                )
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        monkeypatch.setattr(prompt_telemetry_module, "_HEALTH_LOCK", ObservableLock())
        monkeypatch.setattr(
            prompt_telemetry_module, "atomic_write", controlled_atomic_write
        )
        older = threading.Thread(
            target=set_health,
            args=("healthy",),
            name="older-healthy",
        )
        newer = threading.Thread(
            target=set_health,
            args=("degraded",),
            name="newer-degraded",
        )

        older.start()
        assert healthy_write_started.wait(timeout=5)
        newer.start()
        try:
            # With the write inside the health lock, the newer transition is
            # now contending. If the write escapes the lock, this event is set
            # only after the newer degraded marker is durably written. Either
            # ordering makes the historical lost-latch race deterministic.
            assert newer_writer_progressed.wait(timeout=5)
        finally:
            release_healthy_write.set()
        older.join(timeout=5)
        newer.join(timeout=5)

        assert not older.is_alive()
        assert not newer.is_alive()
        assert errors == []
        marker = json.loads(
            prompt_telemetry_health_path(
                telemetry._config.cost_inferences_path
            ).read_text()
        )
        assert marker["status"] == "degraded"
        assert marker["dropped_writes"] == 1

    def test_record_writes_pr_rollup(self, telemetry):
        telemetry.record(
            source="reviewer",
            tool="claude",
            model="sonnet",
            issue_number=42,
            pr_number=101,
            session_id="sess-1",
            prompt_chars=800,
            transcript_chars=400,
            duration_seconds=2.5,
            success=True,
            stats={
                "history_chars_before": 200,
                "history_chars_after": 100,
                "context_chars_before": 1200,
                "context_chars_after": 900,
                "cache_hits": 2,
                "cache_misses": 1,
            },
        )

        pr_file = telemetry._config.pr_stats_path
        assert pr_file.exists()

        rollup = json.loads(pr_file.read_text())
        pr = rollup["prs"]["101"]
        assert pr["inference_calls"] == 1
        assert pr["history_chars_saved"] == 100
        assert pr["context_chars_saved"] == 300
        assert pr["actual_usage_calls"] == 0

    def test_record_writes_lifetime_totals(self, telemetry):
        telemetry.record(
            source="reviewer",
            tool="claude",
            model="sonnet",
            issue_number=42,
            pr_number=101,
            session_id="sess-1",
            prompt_chars=800,
            transcript_chars=400,
            duration_seconds=2.5,
            success=True,
            stats={
                "history_chars_before": 200,
                "history_chars_after": 100,
                "context_chars_before": 1200,
                "context_chars_after": 900,
                "cache_hits": 2,
                "cache_misses": 1,
            },
        )

        inf_file = telemetry._config.cost_inferences_path
        row = json.loads(
            [ln for ln in inf_file.read_text().splitlines() if ln.strip()][0]
        )

        pr_file = telemetry._config.pr_stats_path
        rollup = json.loads(pr_file.read_text())

        lifetime = rollup["lifetime"]
        assert lifetime["inference_calls"] == 1
        assert lifetime["total_tokens"] == row["total_tokens"]
        session = rollup["sessions"]["sess-1"]
        assert session["inference_calls"] == 1
        assert session["total_tokens"] == row["total_tokens"]
        assert rollup["issues"]["42"]["inference_calls"] == 1
        assert rollup["sources"]["reviewer"]["inference_calls"] == 1

    def test_record_prefers_actual_usage_when_available(self, telemetry):
        telemetry.record(
            source="implementer",
            tool="claude",
            model="opus",
            issue_number=7,
            pr_number=202,
            session_id="sess-2",
            prompt_chars=1000,
            transcript_chars=500,
            duration_seconds=1.0,
            success=True,
            stats={"input_tokens": 123, "output_tokens": 77, "total_tokens": 200},
        )

        inf_file = telemetry._config.cost_inferences_path
        row = json.loads(inf_file.read_text().strip())
        assert row["token_source"] == "actual"
        assert row["input_tokens"] == 123
        assert row["output_tokens"] == 77
        assert row["total_tokens"] == 200

        pr_file = telemetry._config.pr_stats_path
        rollup = json.loads(pr_file.read_text())
        pr = rollup["prs"]["202"]
        assert pr["total_tokens"] == 200
        assert pr["actual_usage_calls"] == 1
        assert pr["usage_unavailable_calls"] == 0
        assert rollup["lifetime"]["total_tokens"] == 200
        assert rollup["sessions"]["sess-2"]["total_tokens"] == 200

    def test_input_output_only_stats_are_usage_bearing(self, telemetry):
        """#11117: a call reporting real input/output tokens but no pre-summed
        `total_tokens` is usage-bearing — `usage_status` must be decided AFTER
        the input+output fallback, or the call inflates the anomaly counter
        and gets zeroed out of `prompt_efficiency`'s effective-call
        denominators."""
        telemetry.record(
            source="implementer",
            tool="claude",
            model="opus",
            issue_number=7,
            pr_number=203,
            session_id="sess-io",
            prompt_chars=1000,
            transcript_chars=500,
            duration_seconds=1.0,
            success=True,
            stats={"input_tokens": 123, "output_tokens": 77},
        )

        row = json.loads(telemetry._config.cost_inferences_path.read_text().strip())
        assert row["token_source"] == "actual"
        assert row["usage_status"] == "available"
        assert row["total_tokens"] == 200

        rollup = json.loads(telemetry._config.pr_stats_path.read_text())
        assert rollup["prs"]["203"]["usage_unavailable_calls"] == 0
        assert rollup["prs"]["203"]["actual_usage_calls"] == 1

    def test_accumulator_mirrors_unavailable_cost(self):
        """#11152 review find: cost recorded by usage-unavailable calls needs
        its own accumulator so `prompt_efficiency` can subtract it from rate
        numerators (same-population math)."""
        from prompt_telemetry import PromptTelemetry

        target: dict[str, object] = {}
        PromptTelemetry._accumulate_counter(
            target,
            {
                "usage_status": "unavailable",
                "token_source": "estimated",
                "estimated_cost_usd": 0.002,
                "timestamp": "t1",
            },
        )
        assert target["estimated_cost_microusd"] == 2000
        assert target["unavailable_est_cost_microusd"] == 2000

        PromptTelemetry._accumulate_counter(
            target,
            {
                "usage_status": "available",
                "token_source": "actual",
                "estimated_cost_usd": 0.01,
                "timestamp": "t2",
            },
        )
        assert target["estimated_cost_microusd"] == 12000
        # Usage-bearing cost never lands in the unavailable accumulator.
        assert target["unavailable_est_cost_microusd"] == 2000

    def test_record_marks_usage_unavailable_when_backend_reports_none(self, telemetry):
        telemetry.record(
            source="triage",
            tool="codex",
            model="gpt-5.3-codex",
            issue_number=9,
            pr_number=0,
            session_id="sess-none",
            prompt_chars=100,
            transcript_chars=50,
            duration_seconds=0.3,
            success=True,
            stats={
                "usage_status": "unavailable",
                "usage_available": False,
                "raw_usage": [
                    {"backend": "pi", "event_type": "agent_end", "payload": {}}
                ],
            },
        )

        inf_file = telemetry._config.cost_inferences_path
        row = json.loads(inf_file.read_text().strip())
        assert row["usage_status"] == "unavailable"
        assert row["usage_available"] is False
        assert isinstance(row["raw_usage"], list)

        rollup = json.loads(telemetry._config.pr_stats_path.read_text())
        assert rollup["lifetime"]["usage_unavailable_calls"] == 1

    def test_get_session_and_lifetime_totals(self, telemetry):
        telemetry.record(
            source="planner",
            tool="claude",
            model="opus",
            issue_number=1,
            pr_number=0,
            session_id="sess-3",
            prompt_chars=200,
            transcript_chars=100,
            duration_seconds=0.2,
            success=True,
            stats={"total_tokens": 50},
        )
        telemetry.record(
            source="reviewer",
            tool="claude",
            model="sonnet",
            issue_number=2,
            pr_number=300,
            session_id="sess-4",
            prompt_chars=200,
            transcript_chars=100,
            duration_seconds=0.2,
            success=True,
            stats={"total_tokens": 70},
        )
        assert telemetry.get_lifetime_totals()["total_tokens"] == 120
        assert telemetry.get_session_totals("sess-3")["total_tokens"] == 50
        assert telemetry.get_pr_totals(300)["total_tokens"] == 70
        assert telemetry.get_issue_totals()[2]["total_tokens"] == 70
        assert telemetry.get_source_totals()["reviewer"]["total_tokens"] == 70


class TestGetSourceRegimes:
    """#11280: `get_source_regimes()` tracks each source's most-recently
    recorded model, so `prompt_efficiency` can null a trend across a
    pricing-regime change instead of blending claude and glm windows."""

    def test_empty_before_any_records(self, telemetry):
        assert telemetry.get_source_regimes() == {}

    def test_returns_latest_model_per_source(self, telemetry):
        telemetry.record(
            source="diff-sanity",
            tool="claude",
            model="claude-sonnet-4-5",
            issue_number=1,
            pr_number=0,
            session_id="sess-1",
            prompt_chars=100,
            transcript_chars=50,
            duration_seconds=0.1,
            success=True,
            stats={"total_tokens": 10},
        )
        assert telemetry.get_source_regimes() == {"diff-sanity": "claude-sonnet-4-5"}

    def test_model_switch_overwrites_not_blends(self, telemetry):
        """The GLM-switch scenario: the source's regime tracks the LATEST
        call's model, not a history of every model it has ever seen."""
        for model in ("claude-sonnet-4-5", "claude-sonnet-4-5", "glm-5.2"):
            telemetry.record(
                source="diff-sanity",
                tool="claude",
                model=model,
                issue_number=1,
                pr_number=0,
                session_id="sess-1",
                prompt_chars=100,
                transcript_chars=50,
                duration_seconds=0.1,
                success=True,
                stats={"total_tokens": 10},
            )
        assert telemetry.get_source_regimes() == {"diff-sanity": "glm-5.2"}

    def test_source_totals_unaffected_by_regime_tracking(self, telemetry):
        """`get_source_totals()`'s int-only filter still drops the new
        `last_model` string field — no shape change to the existing surface."""
        telemetry.record(
            source="diff-sanity",
            tool="claude",
            model="glm-5.2",
            issue_number=1,
            pr_number=0,
            session_id="sess-1",
            prompt_chars=100,
            transcript_chars=50,
            duration_seconds=0.1,
            success=True,
            stats={"total_tokens": 10},
        )
        assert "last_model" not in telemetry.get_source_totals()["diff-sanity"]

    def test_load_inferences_reads_recent_rows(self, telemetry):
        telemetry.record(
            source="planner",
            tool="claude",
            model="opus",
            issue_number=10,
            pr_number=0,
            session_id="sess-1",
            prompt_chars=120,
            transcript_chars=30,
            duration_seconds=0.1,
            success=True,
            stats={"total_tokens": 12},
        )
        telemetry.record(
            source="implementer",
            tool="codex",
            model="gpt-5",
            issue_number=11,
            pr_number=400,
            session_id="sess-2",
            prompt_chars=200,
            transcript_chars=40,
            duration_seconds=0.2,
            success=True,
            stats={"total_tokens": 20},
        )

        rows = telemetry.load_inferences(limit=1)
        assert len(rows) == 1
        assert rows[0]["issue_number"] == 11

    def test_failed_empty_run_does_not_estimate_tokens(self, telemetry):
        telemetry.record(
            source="implementer",
            tool="codex",
            model="gpt-5",
            issue_number=13,
            pr_number=0,
            session_id="sess-fail",
            prompt_chars=5000,
            transcript_chars=0,
            duration_seconds=0.05,
            success=False,
            stats={},
        )

        inf_file = telemetry._config.cost_inferences_path
        row = json.loads(inf_file.read_text().strip())
        assert row["status"] == "failed"
        assert row["token_source"] == "estimated"
        assert row["total_est_tokens"] == 0
        assert row["total_tokens"] == 0

    def test_record_prefers_explicit_pruned_counter_and_section_chars(self, telemetry):
        telemetry.record(
            source="planner",
            tool="claude",
            model="opus",
            issue_number=44,
            pr_number=500,
            session_id="sess-prune",
            prompt_chars=120,
            transcript_chars=30,
            duration_seconds=0.1,
            success=True,
            stats={
                "history_chars_before": 1000,
                "history_chars_after": 700,
                "context_chars_before": 2000,
                "context_chars_after": 1800,
                "pruned_chars_total": 123,
                "section_chars": {"issue_body_before": 1000, "issue_body_after": 700},
            },
        )
        inf_file = telemetry._config.cost_inferences_path
        row = json.loads(inf_file.read_text().strip())
        assert row["pruned_chars_total"] == 123
        assert row["section_chars"]["issue_body_before"] == 1000

        pr_file = telemetry._config.pr_stats_path
        rollup = json.loads(pr_file.read_text())
        assert rollup["prs"]["500"]["pruned_chars_total"] == 123

    def test_record_derives_pruned_counter_when_explicit_missing(self, telemetry):
        telemetry.record(
            source="planner",
            tool="claude",
            model="opus",
            issue_number=45,
            pr_number=501,
            session_id="sess-prune",
            prompt_chars=120,
            transcript_chars=30,
            duration_seconds=0.1,
            success=True,
            stats={
                "history_chars_before": 1000,
                "history_chars_after": 700,
                "context_chars_before": 2000,
                "context_chars_after": 1800,
            },
        )
        inf_file = telemetry._config.cost_inferences_path
        row = json.loads(inf_file.read_text().strip())
        assert row["pruned_chars_total"] == 500

    def test_get_mtime_returns_zero_when_no_file(self, telemetry):
        assert telemetry.get_mtime() == 0.0

    def test_get_mtime_returns_positive_after_record(self, telemetry):
        telemetry.record(
            source="planner",
            tool="claude",
            model="opus",
            issue_number=1,
            pr_number=0,
            session_id="s1",
            prompt_chars=10,
            transcript_chars=5,
            duration_seconds=0.1,
            success=True,
            stats={},
        )
        mtime = telemetry.get_mtime()
        assert mtime > 0.0

    def test_record_includes_estimated_cost_for_known_model(self, tmp_path):
        pricing_path = tmp_path / "pricing.json"
        pricing_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "models": {
                        "claude-sonnet-4-20250514": {
                            "input_cost_per_million": 3.0,
                            "output_cost_per_million": 15.0,
                            "aliases": ["sonnet"],
                        }
                    },
                }
            )
        )
        config = ConfigFactory.create(repo_root=tmp_path)
        pricing = ModelPricingTable(pricing_path)
        telemetry = PromptTelemetry(config, pricing=pricing)
        telemetry.record(
            source="reviewer",
            tool="claude",
            model="sonnet",
            issue_number=50,
            pr_number=600,
            session_id="sess-cost",
            prompt_chars=800,
            transcript_chars=400,
            duration_seconds=1.0,
            success=True,
            stats={"input_tokens": 1000, "output_tokens": 500},
        )
        inf_file = config.cost_inferences_path
        row = json.loads(inf_file.read_text().strip())
        assert row["estimated_cost_usd"] is not None
        assert row["estimated_cost_usd"] > 0
        expected = (3.0 * 1000 + 15.0 * 500) / 1_000_000
        assert abs(row["estimated_cost_usd"] - expected) < 1e-6

    def test_record_cost_none_for_unknown_model(self, tmp_path):
        pricing_path = tmp_path / "pricing.json"
        pricing_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "models": {},
                }
            )
        )
        config = ConfigFactory.create(repo_root=tmp_path)
        pricing = ModelPricingTable(pricing_path)
        telemetry = PromptTelemetry(config, pricing=pricing)
        telemetry.record(
            source="reviewer",
            tool="claude",
            model="unknown-model",
            issue_number=51,
            pr_number=601,
            session_id="sess-nocost",
            prompt_chars=100,
            transcript_chars=50,
            duration_seconds=0.5,
            success=True,
            stats={},
        )
        inf_file = config.cost_inferences_path
        row = json.loads(inf_file.read_text().strip())
        assert row["estimated_cost_usd"] is None

    def test_cost_accumulates_across_records(self, tmp_path):
        pricing_path = tmp_path / "pricing.json"
        pricing_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "models": {
                        "claude-opus-4-20250514": {
                            "input_cost_per_million": 15.0,
                            "output_cost_per_million": 75.0,
                            "aliases": ["opus"],
                        }
                    },
                }
            )
        )
        config = ConfigFactory.create(repo_root=tmp_path)
        pricing = ModelPricingTable(pricing_path)
        telemetry = PromptTelemetry(config, pricing=pricing)
        for _ in range(3):
            telemetry.record(
                source="implementer",
                tool="claude",
                model="opus",
                issue_number=52,
                pr_number=700,
                session_id="sess-accum",
                prompt_chars=100,
                transcript_chars=50,
                duration_seconds=0.1,
                success=True,
                stats={"input_tokens": 1000, "output_tokens": 200},
            )
        pr_file = config.pr_stats_path
        rollup = json.loads(pr_file.read_text())
        pr_cost = rollup["prs"]["700"]["estimated_cost_usd"]
        single_cost = (15.0 * 1000 + 75.0 * 200) / 1_000_000
        assert abs(pr_cost - round(single_cost * 3, 6)) < 1e-6


class TestEstimatedCostMicrousdAccumulator:
    """`estimated_cost_microusd` (spec §5 / prompt_efficiency): an int mirror
    of the float `estimated_cost_usd` accumulator. `get_source_totals()` (and
    its lifetime/session/PR/issue siblings) filter aggregate payloads to
    `isinstance(v, int)`, silently dropping `estimated_cost_usd` — this
    accumulator is what lets per-source cost survive that filter."""

    def test_source_totals_carries_cost_as_microusd_int(self, tmp_path):
        pricing_path = tmp_path / "pricing.json"
        pricing_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "models": {
                        "claude-sonnet-4-20250514": {
                            "input_cost_per_million": 3.0,
                            "output_cost_per_million": 15.0,
                            "aliases": ["sonnet"],
                        }
                    },
                }
            )
        )
        config = ConfigFactory.create(repo_root=tmp_path)
        pricing = ModelPricingTable(pricing_path)
        telemetry = PromptTelemetry(config, pricing=pricing)
        telemetry.record(
            source="diff-sanity",
            tool="claude",
            model="sonnet",
            issue_number=60,
            pr_number=800,
            session_id="sess-microusd",
            prompt_chars=800,
            transcript_chars=400,
            duration_seconds=1.0,
            success=True,
            stats={"input_tokens": 1000, "output_tokens": 500},
        )
        source_totals = telemetry.get_source_totals()
        expected_usd = (3.0 * 1000 + 15.0 * 500) / 1_000_000
        expected_microusd = round(expected_usd * 1_000_000)
        entry = source_totals["diff-sanity"]
        assert entry["estimated_cost_microusd"] == expected_microusd
        # It's an int — unlike `estimated_cost_usd`, which the int-only
        # filter in `get_source_totals()` drops.
        assert isinstance(entry["estimated_cost_microusd"], int)
        assert "estimated_cost_usd" not in entry

    def test_accumulates_across_records_for_same_source(self, tmp_path):
        pricing_path = tmp_path / "pricing.json"
        pricing_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "models": {
                        "claude-opus-4-20250514": {
                            "input_cost_per_million": 15.0,
                            "output_cost_per_million": 75.0,
                            "aliases": ["opus"],
                        }
                    },
                }
            )
        )
        config = ConfigFactory.create(repo_root=tmp_path)
        pricing = ModelPricingTable(pricing_path)
        telemetry = PromptTelemetry(config, pricing=pricing)
        for _ in range(3):
            telemetry.record(
                source="test-adequacy",
                tool="claude",
                model="opus",
                issue_number=61,
                pr_number=801,
                session_id="sess-microusd-accum",
                prompt_chars=100,
                transcript_chars=50,
                duration_seconds=0.1,
                success=True,
                stats={"input_tokens": 1000, "output_tokens": 200},
            )
        single_microusd = round((15.0 * 1000 + 75.0 * 200) / 1_000_000 * 1_000_000)
        entry = telemetry.get_source_totals()["test-adequacy"]
        assert entry["estimated_cost_microusd"] == single_microusd * 3

    def test_zero_cost_record_leaves_microusd_at_zero(self, tmp_path):
        """No pricing entry => `estimated_cost_usd` is None => the microusd
        accumulator stays at its `_new_counter()` default of 0 (matches the
        existing lazy `estimated_cost_usd` accumulation, which also skips
        cost-less records)."""
        pricing_path = tmp_path / "pricing.json"
        pricing_path.write_text(json.dumps({"schema_version": 1, "models": {}}))
        config = ConfigFactory.create(repo_root=tmp_path)
        pricing = ModelPricingTable(pricing_path)
        telemetry = PromptTelemetry(config, pricing=pricing)
        telemetry.record(
            source="scope-check",
            tool="claude",
            model="unknown-model",
            issue_number=62,
            pr_number=802,
            session_id="sess-microusd-zero",
            prompt_chars=100,
            transcript_chars=50,
            duration_seconds=0.1,
            success=True,
            stats={},
        )
        entry = telemetry.get_source_totals()["scope-check"]
        assert entry.get("estimated_cost_microusd", 0) == 0


class TestAsFloat:
    def test_int_value(self):
        assert _as_float(42) == 42.0

    def test_float_value(self):
        assert _as_float(3.14) == 3.14

    def test_string_value(self):
        assert _as_float("2.5") == 2.5

    def test_invalid_string(self):
        assert _as_float("not_a_number") == 0.0

    def test_bool_value(self):
        assert _as_float(True) == 1.0

    def test_none_value(self):
        assert _as_float(None) == 0.0


class TestZeroUsageSanityGuard:
    """A 'successful' run that produced zero actual tokens with a non-trivial
    prompt is almost always a CLI-swallowed API rejection (spend cap, 400
    error, etc.). Guard: do not estimate phantom cost, re-classify as failed,
    and tag the record so it is observable.
    """

    def test_reclassifies_success_with_zero_usage_as_failed(self, telemetry):
        """success=True + all actual tokens zero + prompt_chars > 500 => status='failed'."""
        telemetry.record(
            source="triage",
            tool="claude",
            model="sonnet",
            issue_number=9001,
            pr_number=None,
            session_id="sess-zero",
            prompt_chars=21404,
            transcript_chars=229,
            duration_seconds=1.9,
            success=True,
            stats={
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "total_tokens": 0,
                "usage_available": False,
                "usage_status": "unavailable",
            },
        )
        inf_file = telemetry._config.cost_inferences_path
        row = json.loads(
            [ln for ln in inf_file.read_text().splitlines() if ln.strip()][-1]
        )
        assert row["status"] == "failed"
        assert row["estimated_cost_usd"] == 0.0
        assert row["usage_anomaly"] == "zero_usage_with_prompt"

    def test_leaves_legitimate_successful_run_untouched(self, telemetry):
        """success=True with actual tokens reported is a real call — no reclassification."""
        telemetry.record(
            source="implementer",
            tool="claude",
            model="opus",
            issue_number=9002,
            pr_number=None,
            session_id="sess-ok",
            prompt_chars=5000,
            transcript_chars=2000,
            duration_seconds=10.0,
            success=True,
            stats={
                "input_tokens": 1200,
                "output_tokens": 400,
                "total_tokens": 1600,
                "usage_available": True,
                "usage_status": "available",
            },
        )
        inf_file = telemetry._config.cost_inferences_path
        row = json.loads(
            [ln for ln in inf_file.read_text().splitlines() if ln.strip()][-1]
        )
        assert row["status"] == "success"
        assert row.get("usage_anomaly") is None
        assert row["estimated_cost_usd"] > 0

    def test_leaves_tiny_prompt_runs_alone(self, telemetry):
        """Prompts under the threshold may legitimately return zero tokens (stub/no-op); don't touch them."""
        telemetry.record(
            source="triage",
            tool="claude",
            model="sonnet",
            issue_number=9003,
            pr_number=None,
            session_id="sess-tiny",
            prompt_chars=100,
            transcript_chars=0,
            duration_seconds=0.5,
            success=True,
            stats={
                "input_tokens": 0,
                "output_tokens": 0,
                "usage_available": False,
                "usage_status": "unavailable",
            },
        )
        inf_file = telemetry._config.cost_inferences_path
        row = json.loads(
            [ln for ln in inf_file.read_text().splitlines() if ln.strip()][-1]
        )
        assert row["status"] == "success"
        assert row.get("usage_anomaly") is None

    def test_already_failed_runs_not_relabeled_but_still_zero_cost(self, telemetry):
        """Failed runs stay failed; no phantom estimated cost either."""
        telemetry.record(
            source="reviewer",
            tool="claude",
            model="sonnet",
            issue_number=9004,
            pr_number=None,
            session_id="sess-fail",
            prompt_chars=8000,
            transcript_chars=0,
            duration_seconds=5.0,
            success=False,
            stats={
                "input_tokens": 0,
                "output_tokens": 0,
                "usage_available": False,
                "usage_status": "unavailable",
            },
        )
        inf_file = telemetry._config.cost_inferences_path
        row = json.loads(
            [ln for ln in inf_file.read_text().splitlines() if ln.strip()][-1]
        )
        assert row["status"] == "failed"
        assert row["estimated_cost_usd"] == 0.0

    def test_failed_run_with_real_tokens_preserves_cost(self, telemetry):
        """A genuine failure after partial billing must preserve real-token cost.
        The spend-cap guard zeroes cost ONLY when the API emitted zero tokens
        (rejected before billing). A network error after streaming 50k tokens
        must keep its real cost in the record.
        """
        telemetry.record(
            source="implementer",
            tool="claude",
            model="sonnet",
            issue_number=9005,
            pr_number=None,
            session_id="sess-partial",
            prompt_chars=30000,
            transcript_chars=5000,
            duration_seconds=60.0,
            success=False,  # genuine failure
            stats={
                "input_tokens": 50000,  # but tokens were already billed
                "output_tokens": 8000,
                "total_tokens": 58000,
                "usage_available": True,
                "usage_status": "available",
            },
        )
        inf_file = telemetry._config.cost_inferences_path
        row = json.loads(
            [ln for ln in inf_file.read_text().splitlines() if ln.strip()][-1]
        )
        assert row["status"] == "failed"
        assert row.get("usage_anomaly") is None
        # Real tokens were billed — cost must reflect that, not be zeroed out.
        assert row["estimated_cost_usd"] > 0


class TestHashChaining:
    """CH-1 (#9729): inference telemetry rows are hash-chained."""

    def _record(self, telemetry: PromptTelemetry, *, issue: int = 1) -> None:
        telemetry.record(
            source="reviewer",
            tool="claude",
            model="sonnet",
            issue_number=issue,
            pr_number=None,
            session_id="s1",
            prompt_chars=100,
            transcript_chars=200,
            duration_seconds=1.0,
            success=True,
        )

    def test_record_writes_chained_rows(self, telemetry, tmp_path):
        from audit_chain import GENESIS_PREV_HASH

        self._record(telemetry, issue=1)
        self._record(telemetry, issue=2)

        rows = telemetry.load_inferences()
        assert rows[0]["prev_hash"] == GENESIS_PREV_HASH
        assert rows[1]["prev_hash"] == rows[0]["record_hash"]

    def test_recorded_chain_verifies(self, telemetry, tmp_path):
        from audit_chain import AuditChain

        config = ConfigFactory.create(repo_root=tmp_path)
        self._record(telemetry)
        self._record(telemetry)
        result = AuditChain(config.cost_inferences_path).verify()
        assert result.ok
        assert result.chained_records == 2

    def test_pr_stats_still_accumulate(self, telemetry):
        self._record(telemetry)
        totals = telemetry.get_lifetime_totals()
        assert totals["inference_calls"] == 1


class TestRecordNeverRaises:
    """Telemetry must never take down the operation it documents.

    ``record`` runs unguarded in BaseRunner._execute's ``finally`` — a raise
    here converts a SUCCESSFUL agent run into a hard failure and burns
    attempt budget.
    """

    def _record_with_stats(self, telemetry, stats: dict[str, object]) -> None:
        telemetry.record(
            source="implementer",
            tool="claude",
            model="sonnet",
            issue_number=7,
            pr_number=None,
            session_id="sess-nan",
            prompt_chars=100,
            transcript_chars=200,
            duration_seconds=1.0,
            success=True,
            stats=stats,
        )

    def test_non_finite_raw_usage_round_trips_and_lands(self, telemetry):
        """A NaN in a backend raw_usage payload must not raise AND the record
        must still land in the stream (evidence-grade: keep the odd value)."""
        self._record_with_stats(
            telemetry,
            {
                "raw_usage": [
                    {
                        "backend": "claude",
                        "event_type": "result",
                        "payload": {"tokens_per_second": float("nan")},
                    }
                ]
            },
        )

        inf_file = telemetry._config.cost_inferences_path
        rows = [
            json.loads(ln) for ln in inf_file.read_text().splitlines() if ln.strip()
        ]
        assert len(rows) == 1
        assert rows[0]["raw_usage"][0]["payload"]["tokens_per_second"] == "NaN"

        from audit_chain import AuditChain

        assert AuditChain(inf_file).verify().ok

    def test_value_error_from_chain_append_is_swallowed(
        self, telemetry, monkeypatch, caplog
    ):
        """Belt-and-braces: even an unforeseen ValueError from the append
        path (e.g. a scrub-path JSONDecodeError) must not propagate."""

        def _boom(_record):
            raise ValueError("uncanonicalizable payload")

        monkeypatch.setattr(telemetry._chain, "append", _boom)

        with caplog.at_level("WARNING", logger="hydraflow.prompt_telemetry"):
            self._record_with_stats(telemetry, {})

        assert any("prompt telemetry" in r.getMessage().lower() for r in caplog.records)
