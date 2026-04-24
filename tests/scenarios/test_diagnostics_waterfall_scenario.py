"""End-to-end scenario: diagnostics waterfall endpoint (§4.11p2 Task 16).

Seeds per-issue telemetry on disk (inferences + subprocess trace) as if a
pipeline run had just completed, stands up the diagnostics router behind a
FastAPI TestClient, and asserts the ``/api/diagnostics/issue/{N}/waterfall``
payload matches the spec shape the UI components consume.

The route already has unit-level integration coverage in
``tests/test_diagnostics_waterfall_route.py``. This scenario is the release
gate that the route is reachable via TestClient with realistic seeded data
and returns the documented top-level keys (``issue``, ``title``, ``labels``,
``total``, ``phases``, ``missing_phases``) and per-phase keys the
``WaterfallView`` React component depends on (``phase``, ``cost_usd``,
``tokens_in``/``tokens_out``, ``wall_clock_seconds``, ``actions``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard_routes._diagnostics_routes import build_diagnostics_router

pytestmark = pytest.mark.scenario_loops


def _write_inference(data_root: Path, **fields: Any) -> None:
    prompt_dir = data_root / "metrics" / "prompt"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    with (prompt_dir / "inferences.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fields) + "\n")


def _write_subprocess_trace(
    data_root: Path,
    issue: int,
    phase: str,
    run_id: int,
    idx: int,
    payload: dict[str, Any],
) -> None:
    d = data_root / "traces" / str(issue) / phase / f"run-{run_id}"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"subprocess-{idx}.json").write_text(json.dumps(payload), encoding="utf-8")


class TestDiagnosticsWaterfallScenario:
    """§4.11p2 Task 16 — diagnostics waterfall end-to-end scenario."""

    def test_waterfall_endpoint_returns_spec_shape_for_seeded_issue(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Seed two phases + one subprocess trace, hit the route, validate shape."""
        issue_n = 4242
        t0 = "2026-04-22T10:00:00+00:00"
        t1 = "2026-04-22T10:05:00+00:00"
        t2 = "2026-04-22T10:10:00+00:00"

        # Seed two inferences attributed to different runners (= different
        # canonical phases via tracing_context.source_to_phase).
        _write_inference(
            tmp_path,
            timestamp=t0,
            source="triage",
            tool="claude",
            model="claude-sonnet-4-6",
            issue_number=issue_n,
            input_tokens=120,
            output_tokens=40,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
            duration_seconds=2,
            status="success",
        )
        _write_inference(
            tmp_path,
            timestamp=t1,
            source="implementer",
            tool="claude",
            model="claude-sonnet-4-6",
            issue_number=issue_n,
            input_tokens=800,
            output_tokens=250,
            cache_creation_input_tokens=20,
            cache_read_input_tokens=60,
            duration_seconds=45,
            status="success",
        )
        # Seed a subprocess trace (bash tool_call + one passed skill) so the
        # implement phase also surfaces "subprocess" and "skill" action kinds.
        _write_subprocess_trace(
            tmp_path,
            issue_n,
            "implement",
            1,
            1,
            {
                "issue_number": issue_n,
                "phase": "implement",
                "source": "implementer",
                "run_id": 1,
                "subprocess_idx": 1,
                "backend": "claude",
                "started_at": t1,
                "ended_at": t2,
                "success": True,
                "tokens": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cache_read_tokens": 0,
                    "cache_creation_tokens": 0,
                    "cache_hit_rate": 0.0,
                },
                "tools": {
                    "tool_counts": {"Bash": 1},
                    "tool_errors": {},
                    "total_invocations": 1,
                },
                "tool_calls": [
                    {
                        "tool_name": "Bash",
                        "started_at": t1,
                        "duration_ms": 1500,
                        "input_summary": "pytest tests/",
                        "succeeded": True,
                        "tool_use_id": "t-1",
                    },
                ],
                "skill_results": [
                    {
                        "skill_name": "diff-sanity",
                        "passed": True,
                        "attempts": 1,
                        "duration_seconds": 1.5,
                        "blocking": True,
                    },
                ],
                "inference_count": 0,
                "turn_count": 0,
            },
        )

        # Minimal HydraFlowConfig stand-in — the waterfall route only needs
        # data_root (for traces) and data_path (used by _cost_rollups to
        # resolve inferences.jsonl).
        config = MagicMock()
        config.data_root = tmp_path
        config.data_path = tmp_path.joinpath
        config.factory_metrics_path = tmp_path / "diagnostics" / "factory_metrics.jsonl"
        config.repo = "o/r"

        # Bypass GitHub — the waterfall route calls fetch_issue_by_number
        # to hydrate issue_meta. We inject a fake fetcher that returns a
        # synthetic GitHubIssue-shaped MagicMock.
        fetcher = MagicMock()
        fetcher.fetch_issue_by_number = AsyncMock(
            return_value=MagicMock(
                number=issue_n,
                title="Scenario issue",
                labels=["hydraflow-ready"],
                created_at=t0,
            ),
        )
        monkeypatch.setattr(
            "dashboard_routes._diagnostics_routes._build_issue_fetcher",
            lambda cfg: fetcher,
        )

        app = FastAPI()
        app.include_router(build_diagnostics_router(config))
        client = TestClient(app)

        resp = client.get(f"/api/diagnostics/issue/{issue_n}/waterfall")
        assert resp.status_code == 200, resp.text
        payload = resp.json()

        # --- Top-level shape the UI contract depends on -------------------
        assert payload["issue"] == issue_n
        assert payload["title"] == "Scenario issue"
        assert "hydraflow-ready" in payload["labels"]
        assert set(payload.keys()) >= {
            "issue",
            "title",
            "labels",
            "total",
            "phases",
            "missing_phases",
        }

        # --- total aggregates reflect seeded inferences -------------------
        total = payload["total"]
        assert set(total.keys()) >= {
            "tokens_in",
            "tokens_out",
            "cost_usd",
            "wall_clock_seconds",
        }
        # 120 + 800 = 920 tokens_in
        assert total["tokens_in"] >= 920
        # 40 + 250 = 290 tokens_out
        assert total["tokens_out"] >= 290
        # Cost is priced on the fly via ModelPricing.estimate_cost and
        # should be strictly positive for a known model.
        assert total["cost_usd"] > 0.0

        # --- phases contain at least triage + implement -------------------
        phases_seen = {p["phase"] for p in payload["phases"]}
        assert {"triage", "implement"}.issubset(phases_seen), phases_seen

        for phase_entry in payload["phases"]:
            assert set(phase_entry.keys()) >= {
                "phase",
                "cost_usd",
                "tokens_in",
                "tokens_out",
                "wall_clock_seconds",
                "actions",
            }
            assert isinstance(phase_entry["actions"], list)

        # --- implement phase collected all three action kinds -------------
        implement = next(p for p in payload["phases"] if p["phase"] == "implement")
        kinds = {a["kind"] for a in implement["actions"]}
        assert {"llm", "skill", "subprocess"}.issubset(kinds), kinds

        # --- missing_phases lists the canonical phases with zero telemetry
        missing = set(payload["missing_phases"])
        # We never seeded merge/review/shape/discover/plan for this issue.
        assert {"merge", "review"}.issubset(missing), missing
