"""Tests for ``orchestrator_stats`` — the factory's self-report.

Two surfaces, both read-only and both load-bearing for the dashboard:

* ``run_status`` — the lifecycle string. Its branch ORDER is the contract: a
  paused-for-credits factory must not read as "running", and a stopping one
  must not read as "idle".
* ``build_pipeline_stats`` — the ADR-0014 snapshot. The stage set and the
  forward-progression session-counter map are what the dashboard binds to; a
  stage silently dropped from either is invisible until an operator notices a
  blank tile.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from orchestrator import HydraFlowOrchestrator

if TYPE_CHECKING:
    from config import HydraFlowConfig


class TestRunStatus:
    """Lifecycle string, in the precedence order the branches encode."""

    def test_fresh_orchestrator_is_idle(self, config: HydraFlowConfig) -> None:
        assert HydraFlowOrchestrator(config).run_status == "idle"

    def test_running_flag_reads_as_running(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._running = True
        assert orch.run_status == "running"

    def test_stop_requested_while_running_reads_as_stopping(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._running = True
        orch._stop_event.set()
        assert orch.run_status == "stopping"

    def test_live_credit_pause_outranks_running(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._running = True
        orch._credits_paused_until = datetime.now(UTC) + timedelta(hours=1)
        assert orch.run_status == "credits_paused"

    def test_expired_credit_pause_does_not_mask_running(
        self, config: HydraFlowConfig
    ) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._running = True
        orch._credits_paused_until = datetime.now(UTC) - timedelta(seconds=1)
        assert orch.run_status == "running"

    def test_auth_failure_outranks_everything(self, config: HydraFlowConfig) -> None:
        orch = HydraFlowOrchestrator(config)
        orch._running = True
        orch._credits_paused_until = datetime.now(UTC) + timedelta(hours=1)
        orch._auth_failed = True
        assert orch.run_status == "auth_failed"


class TestBuildPipelineStats:
    """The ADR-0014 snapshot shape."""

    _PIPELINE_STAGES = ("triage", "plan", "implement", "review", "hitl")

    @pytest.fixture
    def stats(self, config: HydraFlowConfig):
        return HydraFlowOrchestrator(config).build_pipeline_stats()

    def test_every_pipeline_stage_plus_merged_is_present(self, stats) -> None:
        assert set(stats.stages) == {*self._PIPELINE_STAGES, "merged"}

    def test_worker_caps_come_from_config(self, config: HydraFlowConfig, stats) -> None:
        assert stats.stages["triage"].worker_cap == config.max_triagers
        assert stats.stages["plan"].worker_cap == config.max_planners
        assert stats.stages["implement"].worker_cap == config.max_workers
        assert stats.stages["review"].worker_cap == config.max_reviewers
        assert stats.stages["hitl"].worker_cap == config.max_hitl_workers

    def test_uptime_is_zero_without_a_session(self, stats) -> None:
        assert stats.uptime_seconds == 0.0

    def test_timestamp_is_parseable_utc(self, stats) -> None:
        assert datetime.fromisoformat(stats.timestamp).tzinfo is not None

    def test_hitl_has_no_session_counter(self, stats) -> None:
        # ADR-0014: HITL is the one stage with no forward-progression counter,
        # so it always reports 0 rather than borrowing a neighbour's.
        assert stats.stages["hitl"].completed_session == 0
