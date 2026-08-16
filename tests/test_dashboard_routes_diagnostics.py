"""Tests for the diagnostics dashboard route module."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from dashboard_routes._diagnostics_routes import build_diagnostics_router  # noqa: E402


def _write_metrics(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    config = MagicMock()
    config.data_root = tmp_path
    config.diagnostics_dir = tmp_path / "diagnostics"
    config.factory_metrics_path = tmp_path / "diagnostics" / "factory_metrics.jsonl"

    # Use a recent timestamp so the event stays within all range filters
    # (24h/7d/30d). Hard-coded dates drift out of range over time.
    recent_ts = (
        (datetime.now(UTC) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    )
    _write_metrics(
        config.factory_metrics_path,
        [
            {
                "timestamp": recent_ts,
                "issue": 42,
                "phase": "implement",
                "run_id": 1,
                "tokens": {
                    "input": 1000,
                    "output": 500,
                    "cache_read": 200,
                    "cache_creation": 0,
                },
                "tools": {"Read": 5, "Bash": 2},
                "skills": [
                    {"name": "diff-sanity", "passed": True, "attempts": 1},
                ],
                "subagents": 1,
                "duration_seconds": 120.0,
                "crashed": False,
            },
        ],
    )

    fastapi_app = FastAPI()
    fastapi_app.include_router(build_diagnostics_router(config))
    return fastapi_app


class TestDiagnosticsOverviewEndpoint:
    def test_overview_returns_headline(self, app: FastAPI) -> None:
        client = TestClient(app)
        response = client.get("/api/diagnostics/overview?range=7d")
        assert response.status_code == 200
        body = response.json()
        assert body["total_tokens"] == 1700
        assert body["total_runs"] == 1
        assert body["total_tool_invocations"] == 7
        assert body["total_subagents"] == 1


class TestDiagnosticsToolsEndpoint:
    def test_tools_returns_top(self, app: FastAPI) -> None:
        client = TestClient(app)
        response = client.get("/api/diagnostics/tools?range=7d")
        assert response.status_code == 200
        body = response.json()
        assert body[0]["name"] == "Read"
        assert body[0]["count"] == 5


class TestDiagnosticsSkillsEndpoint:
    def test_skills_returns_first_try_rate(self, app: FastAPI) -> None:
        client = TestClient(app)
        response = client.get("/api/diagnostics/skills?range=7d")
        assert response.status_code == 200
        body = response.json()
        assert body[0]["name"] == "diff-sanity"
        assert body[0]["first_try_pass_rate"] == 1.0


class TestDiagnosticsCostByPhaseEndpoint:
    def test_cost_by_phase(self, app: FastAPI) -> None:
        client = TestClient(app)
        response = client.get("/api/diagnostics/cost-by-phase?range=7d")
        assert response.status_code == 200
        body = response.json()
        assert body["implement"] == 1700


class TestDiagnosticsIssuesEndpoint:
    def test_issues_table(self, app: FastAPI) -> None:
        client = TestClient(app)
        response = client.get("/api/diagnostics/issues?range=7d")
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        assert rows[0]["issue"] == 42


class TestDiagnosticsSubagentsEndpoint:
    def test_subagents_returns_empty_list_for_now(self, app: FastAPI) -> None:
        client = TestClient(app)
        response = client.get("/api/diagnostics/subagents?range=7d")
        assert response.status_code == 200
        assert response.json() == []


class TestDiagnosticsIssueDrillEndpoints:
    def test_issue_phase_lists_run_summaries(
        self, app: FastAPI, tmp_path: Path
    ) -> None:
        run_dir = tmp_path / "traces" / "42" / "implement" / "run-1"
        run_dir.mkdir(parents=True)
        (run_dir / "summary.json").write_text(
            json.dumps({"run_id": 1, "tokens": 1700}), encoding="utf-8"
        )

        client = TestClient(app)
        response = client.get("/api/diagnostics/issue/42/implement")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert body[0]["run_id"] == 1

    def test_issue_phase_run_returns_summary_and_subprocesses(
        self, app: FastAPI, tmp_path: Path
    ) -> None:
        run_dir = tmp_path / "traces" / "42" / "implement" / "run-1"
        run_dir.mkdir(parents=True)
        (run_dir / "summary.json").write_text(
            json.dumps({"run_id": 1}), encoding="utf-8"
        )
        (run_dir / "subprocess-a.json").write_text(
            json.dumps({"name": "a"}), encoding="utf-8"
        )

        client = TestClient(app)
        response = client.get("/api/diagnostics/issue/42/implement/1")
        assert response.status_code == 200
        body = response.json()
        assert body["summary"] == {"run_id": 1}
        assert body["subprocesses"] == [{"name": "a"}]

    def test_issue_phase_run_missing_returns_404(self, app: FastAPI) -> None:
        client = TestClient(app)
        response = client.get("/api/diagnostics/issue/999/implement/1")
        assert response.status_code == 404

    def test_issue_phase_rejects_non_canonical_phase(self, app: FastAPI) -> None:
        client = TestClient(app)
        # Uppercase / space is not in the [a-z_-]+ pattern. Matches the
        # drill-down sibling's 404 behavior so consumers get a consistent
        # error signal for bad phase names.
        response = client.get("/api/diagnostics/issue/42/Plan%20A")
        assert response.status_code == 404

    def test_issue_phase_missing_dir_returns_404(self, app: FastAPI) -> None:
        """A valid phase name with no on-disk directory returns 404."""
        client = TestClient(app)
        response = client.get("/api/diagnostics/issue/999/implement")
        assert response.status_code == 404

    def test_issue_phase_run_rejects_non_canonical_phase(self, app: FastAPI) -> None:
        client = TestClient(app)
        response = client.get("/api/diagnostics/issue/42/Plan%20A/1")
        assert response.status_code == 404


class TestPathTraversalProtection:
    def test_safe_traces_subdir_rejects_parent_traversal(self, tmp_path: Path) -> None:
        from dashboard_routes._diagnostics_routes import _safe_traces_subdir

        assert _safe_traces_subdir(tmp_path, 42, "../../etc") is None
        assert _safe_traces_subdir(tmp_path, 42, "..", "..", "etc") is None

    def test_safe_traces_subdir_accepts_normal_paths(self, tmp_path: Path) -> None:
        from dashboard_routes._diagnostics_routes import _safe_traces_subdir

        result = _safe_traces_subdir(tmp_path, 42, "implement")
        assert result is not None
        assert result == (tmp_path / "traces" / "42" / "implement").resolve()

    def test_phase_traversal_blocked_at_router_level(self, app: FastAPI) -> None:
        """FastAPI/starlette normalizes ``..`` before routing, so a traversal
        attempt never reaches the handler. The phase-list endpoint now
        raises 404 on bad phases to match the drill-down sibling.
        """
        client = TestClient(app)
        response = client.get("/api/diagnostics/issue/42/..%2F..%2Fetc")
        assert response.status_code == 404

    def test_phase_run_traversal_blocked_at_router_level(self, app: FastAPI) -> None:
        client = TestClient(app)
        response = client.get("/api/diagnostics/issue/42/..%2F..%2Fetc/1")
        assert response.status_code == 404


class TestDiagnosticsCacheEndpoint:
    def test_cache_returns_hourly_buckets(self, app: FastAPI) -> None:
        client = TestClient(app)
        response = client.get("/api/diagnostics/cache?range=7d")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)
        assert len(body) == 1
        assert body[0]["cache_hit_rate"] == pytest.approx(200 / 1200, rel=1e-3)


class TestSupervisorAckEndpoint:
    """POST /api/diagnostics/supervisor/ack — append-only escalation ack."""

    def _write_obs(self, path: Path, obs: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(obs) + "\n")

    def test_ack_requires_ts_and_escalation(self, app: FastAPI) -> None:
        client = TestClient(app)
        assert (
            client.post("/api/diagnostics/supervisor/ack", json={}).status_code == 400
        )
        assert (
            client.post(
                "/api/diagnostics/supervisor/ack", json={"ts": "2026-08-02T00:00:00Z"}
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/diagnostics/supervisor/ack", json={"escalation": "force_push"}
            ).status_code
            == 400
        )

    def test_ack_appends_and_thread_join_marks_it_acked(
        self, app: FastAPI, tmp_path: Path
    ) -> None:
        ts = "2026-08-02T17:31:46Z"
        thread = tmp_path / "supervisor_thread.jsonl"
        self._write_obs(
            thread,
            {
                "ts": ts,
                "snapshot": {"healthy": False},
                "assessment": "RC wedged",
                "escalations": [
                    "force_push [main] — RC wedged",
                    "delete_branch — orphan",
                ],
            },
        )
        client = TestClient(app)

        # Before the ack the join reports nothing acknowledged.
        before = client.get("/api/diagnostics/supervisor/thread").json()
        assert before["observations"][0]["acked_escalations"] == []

        resp = client.post(
            "/api/diagnostics/supervisor/ack",
            json={"ts": ts, "escalation": "force_push [main] — RC wedged"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        assert (tmp_path / "supervisor_acks.jsonl").exists()

        # After the ack the join surfaces exactly the acked escalation, leaving
        # the original observation's escalation list intact (honest, rule 6).
        after = client.get("/api/diagnostics/supervisor/thread").json()
        obs = after["observations"][0]
        assert obs["acked_escalations"] == ["force_push [main] — RC wedged"]
        assert len(obs["escalations"]) == 2


class TestTokenReportEndpoint:
    """#11298 measurement layer: /api/diagnostics/token-report."""

    def _app(self, tmp_path: Path, rows: list[dict] | None) -> FastAPI:
        config = MagicMock()
        config.data_root = tmp_path
        config.diagnostics_dir = tmp_path / "diagnostics"
        config.factory_metrics_path = tmp_path / "diagnostics" / "m.jsonl"
        prompt_dir = tmp_path / "metrics" / "prompt"
        config.cost_inferences_path = prompt_dir / "inferences.jsonl"
        config.pr_stats_path = prompt_dir / "pr_stats.json"
        if rows is not None:
            prompt_dir.mkdir(parents=True, exist_ok=True)
            with open(config.cost_inferences_path, "w") as f:
                for row in rows:
                    f.write(json.dumps(row) + "\n")
        fastapi_app = FastAPI()
        fastapi_app.include_router(build_diagnostics_router(config))
        return fastapi_app

    def test_report_rolls_up_real_rows(self, tmp_path: Path) -> None:
        rows = [
            {
                "issue_number": 42,
                "source": "implementer",
                "total_tokens": 90_000,
                "input_tokens": 10_000,
                "cache_read_input_tokens": 30_000,
                "estimated_cost_usd": 0.9,
            },
            {
                "issue_number": 42,
                "source": "planner",
                "total_tokens": 30_000,
                "estimated_cost_usd": 0.3,
            },
        ]
        client = TestClient(self._app(tmp_path, rows))
        response = client.get("/api/diagnostics/token-report")
        assert response.status_code == 200
        payload = response.json()
        assert payload["fleet"]["issues_counted"] == 1
        entry = payload["issues"][0]
        assert entry["issue"] == 42
        assert entry["tokens"] == 120_000
        assert entry["phases"][0]["source"] == "implementer"
        assert entry["cache_hit_rate"] == 0.75
        assert "generated_at" in payload

    def test_missing_telemetry_fails_soft(self, tmp_path: Path) -> None:
        client = TestClient(self._app(tmp_path, None))
        response = client.get("/api/diagnostics/token-report")
        assert response.status_code == 200
        payload = response.json()
        assert payload["issues"] == []
        assert payload["fleet"]["issues_counted"] == 0
