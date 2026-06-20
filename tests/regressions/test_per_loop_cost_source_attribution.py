"""Regression: /api/diagnostics/loops/cost bills LLM spend to the right loop.

The per-loop cost table attributed LLM cost by temporal overlap between a
loop's trace window and inference timestamps. That mechanism billed $0 to
every background worker, because the loops that emit traces are LLM-free
caretaker loops while the LLM-spending workers (pr_unsticker, repo_wiki,
auto_agent_preflight, ...) emit no loop trace at all — and, when windows did
coincide, it mis-charged pipeline spend to whichever caretaker tick overlapped.

Cost is now attributed by the inference ``source`` field. This locks two
behaviors end-to-end through the route:

1. a bg worker that records inferences but emits no loop trace still shows
   non-zero cost;
2. a caretaker loop whose trace window overlaps an unrelated inference is NOT
   charged that inference's cost.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import HydraFlowConfig
from dashboard_routes._diagnostics_routes import build_diagnostics_router
from tests.helpers import ConfigFactory


@pytest.fixture
def config(tmp_path: Path) -> HydraFlowConfig:
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    return ConfigFactory.create(repo_root=tmp_path / "repo")


@pytest.fixture
def client(config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # The route builds an EventBus from disk; the per-loop cost path under test
    # needs none, so stub it out to keep the test hermetic.
    monkeypatch.setattr(
        "dashboard_routes._diagnostics_routes._event_bus_for_rollup",
        lambda cfg: None,
    )
    app = FastAPI()
    app.include_router(build_diagnostics_router(config))
    return TestClient(app)


def _write_inference(config: HydraFlowConfig, **fields: object) -> None:
    config.cost_inferences_path.parent.mkdir(parents=True, exist_ok=True)
    with config.cost_inferences_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


def _write_loop_trace(config: HydraFlowConfig, loop: str, **fields: object) -> None:
    from trace_collector import _slug_for_loop  # noqa: PLC0415

    d = config.data_root / "traces" / "_loops" / _slug_for_loop(loop)
    d.mkdir(parents=True, exist_ok=True)
    payload = {"kind": "loop", "loop": loop, **fields}
    started = str(fields["started_at"])
    (d / f"run-{started.replace(':', '')}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_loops_cost_bills_bg_worker_not_overlapping_caretaker_loop(
    client: TestClient, config: HydraFlowConfig
) -> None:
    now = datetime.now(UTC)
    # A bg worker spends LLM but emits no loop trace. Use the estimated-cost
    # fallback (zero token counts) so cost is deterministic regardless of the
    # live pricing table.
    _write_inference(
        config,
        timestamp=(now - timedelta(minutes=30)).isoformat(),
        source="pr_unsticker",
        model="claude-sonnet-4-6",
        input_tokens=0,
        output_tokens=0,
        estimated_cost_usd=0.5,
    )
    # An LLM-free caretaker loop ticks across the same window.
    _write_loop_trace(
        config,
        "trust_fleet_sanity",
        started_at=(now - timedelta(minutes=40)).isoformat(),
        duration_ms=3_600_000,  # 1h window straddling the inference
        command=["gh", "issue", "list"],
        exit_code=0,
    )

    resp = client.get("/api/diagnostics/loops/cost?range=24h")
    assert resp.status_code == 200
    by_loop = {r["loop"]: r for r in resp.json()}

    assert "pr_unsticker" in by_loop
    assert by_loop["pr_unsticker"]["cost_usd"] == pytest.approx(0.5)
    assert by_loop["pr_unsticker"]["llm_calls"] == 1

    # The caretaker loop ticked but spent nothing — its window must not absorb
    # the bg worker's inference.
    assert by_loop["trust_fleet_sanity"]["cost_usd"] == 0.0
    assert by_loop["trust_fleet_sanity"]["ticks"] == 1
