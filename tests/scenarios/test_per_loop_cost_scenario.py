"""MockWorld-level scenarios for per-loop cost attribution (#9550, #9588).

These are the integration ("scenario_loops") gates for two fixes whose
original bugs were loop-integration failures that unit tests with synthetic
data could not see:

* **#9550** — ``build_per_loop_cost`` attributes LLM cost to a loop by the
  inference ``source`` field, not by temporal overlap with a loop-trace
  window. The original bug: the loops that emit loop traces are LLM-free
  caretaker loops, while the LLM-spending workers emit no trace at all
  (disjoint key spaces) → ``$0`` for every worker. This scenario seeds
  realistic on-disk telemetry (inferences whose ``source`` differs from the
  loop name + a trace for an LLM-free caretaker), drives the real
  ``/api/diagnostics/loops/cost`` route through a TestClient, and asserts
  cost lands on the right loop while the LLM-free caretaker stays at ``$0``.

* **#9588** — ``emit_loop_subprocess_trace`` records ``started_at`` as the
  work START (back-dated by ``duration_ms``), not the emit time. This
  scenario drives a *real* ``WikiRotDetectorLoop`` tick through MockWorld so
  the production helper writes a real trace, then asserts the recorded
  ``started_at + duration_ms`` brackets the actual wall-clock tick interval.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import trace_collector
from dashboard_routes._diagnostics_routes import build_diagnostics_router
from tests.helpers import ConfigFactory
from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


def _write_inference(config: Any, **fields: Any) -> None:
    """Append one inference row to the repo-scoped inferences.jsonl."""
    path = config.cost_inferences_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


def _write_loop_trace(config: Any, loop: str, **fields: Any) -> None:
    """Write a loop trace under data_root/traces/_loops/<slug>/run-*.json."""
    slug = trace_collector._slug_for_loop(loop)
    d = config.data_root / "traces" / "_loops" / slug
    d.mkdir(parents=True, exist_ok=True)
    payload = {"kind": "loop", "loop": loop, **fields}
    started = str(fields["started_at"]).replace(":", "").replace("+", "")
    (d / f"run-{started}.json").write_text(json.dumps(payload), encoding="utf-8")


class TestLoopsCostEndpointScenario:
    """#9550 — /api/diagnostics/loops/cost attributes cost by inference source."""

    def test_cost_attributed_by_source_not_trace_window(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Seed realistic telemetry, hit the real route, assert source-based
        attribution: LLM-spending workers (which emit no trace) show their
        cost; an LLM-free caretaker (which emits a trace) stays at $0."""
        (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
        config = ConfigFactory.create(repo_root=tmp_path / "repo")

        now = datetime.now(UTC)
        recent = (now - timedelta(minutes=30)).isoformat()

        # Bg-worker inferences whose `source` differs from the worker_name.
        _write_inference(
            config,
            timestamp=recent,
            source="wiki_compilation",  # → repo_wiki (alias)
            tool="claude",
            model="claude-sonnet-4-6",
            input_tokens=200,
            output_tokens=80,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            status="success",
        )
        # Both diagnostic stages fold into the single "diagnostic" loop.
        for src in ("diagnostic", "diagnostic_fix"):
            _write_inference(
                config,
                timestamp=recent,
                source=src,
                tool="claude",
                model="claude-sonnet-4-6",
                input_tokens=150,
                output_tokens=50,
                status="success",
            )
        # A pipeline source folds to its canonical phase ("implement").
        _write_inference(
            config,
            timestamp=recent,
            source="implementer",
            tool="claude",
            model="claude-sonnet-4-6",
            input_tokens=500,
            output_tokens=120,
            status="success",
        )
        # A non-loop telemetry artifact must NOT surface a row.
        _write_inference(
            config,
            timestamp=recent,
            source="estimated",
            tool="claude",
            model="claude-sonnet-4-6",
            input_tokens=10,
            output_tokens=5,
            status="success",
        )

        # An LLM-free caretaker loop emits a trace in the same window but
        # records no inference — under the OLD logic it would have absorbed
        # the overlapping spend; under the fix it stays at $0.
        _write_loop_trace(
            config,
            "trust_fleet_sanity",
            started_at=recent,
            duration_ms=1500,
            exit_code=0,
            command=["gh", "issue", "list"],
        )

        # The per-loop cost path under test needs no events.
        monkeypatch.setattr(
            "dashboard_routes._diagnostics_routes._event_bus_for_rollup",
            lambda cfg: None,
        )

        app = FastAPI()
        app.include_router(build_diagnostics_router(config))
        client = TestClient(app)

        resp = client.get("/api/diagnostics/loops/cost?range=24h")
        assert resp.status_code == 200, resp.text
        by_loop = {r["loop"]: r for r in resp.json()}

        # Bg workers show their real cost, keyed by canonical worker name.
        assert by_loop["repo_wiki"]["cost_usd"] > 0.0
        assert by_loop["repo_wiki"]["llm_calls"] == 1
        assert by_loop["diagnostic"]["cost_usd"] > 0.0
        assert by_loop["diagnostic"]["llm_calls"] == 2  # diagnostic + diagnostic_fix
        assert by_loop["implement"]["cost_usd"] > 0.0
        assert by_loop["implement"]["llm_calls"] == 1

        # The LLM-free caretaker ticked (trace) but spent nothing.
        assert by_loop["trust_fleet_sanity"]["ticks"] == 1
        assert by_loop["trust_fleet_sanity"]["cost_usd"] == 0.0

        # Raw source aliases / non-loop artifacts must never surface as rows.
        for raw in ("wiki_compilation", "diagnostic_fix", "estimated", "unsticker"):
            assert raw not in by_loop, raw


class TestLoopTraceStartedAtScenario:
    """#9588 — a real loop tick records started_at as work-start."""

    async def test_loop_tick_emits_work_start_trace(
        self,
        tmp_path: Path,
    ) -> None:
        """Drive a real WikiRotDetectorLoop tick through MockWorld; the
        production emit_loop_subprocess_trace must record started_at back-dated
        by duration_ms (work-start), so started_at + duration_ms lands at the
        tick's wall-clock end rather than one full duration in the future."""
        # The loop's emit reads the process-wide active config; register one
        # whose data_root we control, and restore it afterwards.
        (tmp_path / "trace_cfg").mkdir(parents=True, exist_ok=True)
        trace_cfg = ConfigFactory.create(repo_root=tmp_path / "trace_cfg")
        trace_collector.set_active_config(trace_cfg)
        try:
            world = MockWorld(tmp_path)

            # Empty repo list → fast tick that still reaches _emit_trace
            # (mirrors test_wiki_rot_detector_scenario's reconcile path).
            fake_state = MagicMock()
            fake_state.get_wiki_rot_attempts.return_value = 0
            fake_state.inc_wiki_rot_attempts.return_value = 1
            fake_dedup = MagicMock()
            fake_dedup.get.return_value = set()
            fake_wiki_store = MagicMock()
            # Make the tick take measurable wall-clock time so duration_ms is
            # well above timing jitter. Without this the back-date is sub-ms and
            # indistinguishable from the emit-time bug — i.e. the assertion below
            # would have no teeth. ~150ms makes the emit-time regression (which
            # would push started_at+duration ~150ms past `after`) fail loudly.
            fake_wiki_store.list_repos.side_effect = lambda: time.sleep(0.15) or []

            _seed_ports(
                world,
                wiki_rot_state=fake_state,
                wiki_rot_dedup=fake_dedup,
                wiki_store=fake_wiki_store,
            )

            before = datetime.now(UTC)
            stats = await world.run_with_loops(["wiki_rot_detector"], cycles=1)
            after = datetime.now(UTC)
            assert stats["wiki_rot_detector"] is not None

            trace_dir = trace_cfg.data_root / "traces" / "_loops" / "wiki_rot_detector"
            files = list(trace_dir.glob("run-*.json"))
            assert len(files) == 1, f"expected one emitted trace, got {files}"
            payload = json.loads(files[0].read_text(encoding="utf-8"))

            assert payload["kind"] == "loop"
            assert payload["duration_ms"] >= 0
            started = datetime.fromisoformat(payload["started_at"])
            work_end = started + timedelta(milliseconds=payload["duration_ms"])
            # Back-dated started_at ⇒ work_end falls inside the real tick window.
            # (Under the old emit-time logic, started_at ≈ after, so work_end
            # would overshoot `after` by a full duration.)
            assert before <= work_end <= after, (
                f"started_at not back-dated to work-start: work_end={work_end} "
                f"not in [{before}, {after}]"
            )
        finally:
            trace_collector.set_active_config(None)
