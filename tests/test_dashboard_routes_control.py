"""Tests for dashboard_routes.py — control and config endpoints."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from queue_strategy import QueueStrategy

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus
from tests.helpers import find_endpoint, make_dashboard_router


class TestControlStatusMaxTriagers:
    @pytest.mark.asyncio
    async def test_control_status_includes_max_triagers(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """GET /api/control/status should include max_triagers from config."""

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)

        get_control_status = find_endpoint(router, "/api/control/status")

        assert get_control_status is not None
        response = await get_control_status()
        data = json.loads(response.body)
        assert "config" in data
        assert data["config"]["max_triagers"] == config.max_triagers


class TestControlStatusQueueStrategy:
    @pytest.mark.asyncio
    async def test_control_status_exposes_the_active_queue_strategy(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        # The dashboard reads config.queue_strategy from here to show which
        # algorithm is picking work (#10067); without it the badge is blind.
        config.queue_strategy = QueueStrategy.WEIGHTED_MIX
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        get_control_status = find_endpoint(router, "/api/control/status")
        assert get_control_status is not None

        data = json.loads((await get_control_status()).body)

        assert data["config"]["queue_strategy"] == "weighted_mix"
        assert data["config"]["queue_weight_p1"] == config.queue_weight_p1
        assert data["config"]["queue_weight_p2"] == config.queue_weight_p2
        assert (
            data["config"]["queue_weight_unprioritised"]
            == config.queue_weight_unprioritised
        )


class TestControlStatusAppVersion:
    @pytest.mark.asyncio
    async def test_control_status_includes_app_version(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        from app_version import get_app_version

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)

        get_control_status = find_endpoint(router, "/api/control/status")

        assert get_control_status is not None
        response = await get_control_status()
        data = json.loads(response.body)
        assert data["config"]["app_version"] == get_app_version()

    @pytest.mark.asyncio
    async def test_control_status_includes_cached_update_details(
        self, config, event_bus: EventBus, state, tmp_path: Path, monkeypatch
    ) -> None:
        from update_check import UpdateCheckResult

        monkeypatch.setattr(
            "dashboard_routes._control_routes.load_cached_update_result",
            lambda **_kwargs: UpdateCheckResult(
                current_version="0.9.1",
                latest_version="0.9.2",
                update_available=True,
                error=None,
            ),
        )

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)

        get_control_status = find_endpoint(router, "/api/control/status")

        assert get_control_status is not None
        response = await get_control_status()
        data = json.loads(response.body)
        assert data["config"]["latest_version"] == "0.9.2"
        assert data["config"]["update_available"] is True


class TestControlStatusBootShaCommitsBehind:
    @pytest.mark.asyncio
    async def test_status_includes_boot_sha_and_commits_behind(
        self, config, event_bus: EventBus, state, tmp_path: Path, monkeypatch
    ) -> None:
        """GET /api/control/status projects the in-memory boot SHA and a
        cheap commits-behind count for at-a-glance staleness observability."""
        monkeypatch.setattr(
            "dashboard_routes._control_routes.get_boot_sha",
            lambda: "abc1234deadbeef",
        )
        monkeypatch.setattr(
            "dashboard_routes._control_routes.get_commits_behind",
            lambda: 5,
        )

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)

        get_control_status = find_endpoint(router, "/api/control/status")

        assert get_control_status is not None
        response = await get_control_status()
        data = json.loads(response.body)
        assert data["config"]["boot_sha"] == "abc1234deadbeef"
        assert data["config"]["commits_behind"] == 5

    @pytest.mark.asyncio
    async def test_status_tolerates_unavailable_git(
        self, config, event_bus: EventBus, state, tmp_path: Path, monkeypatch
    ) -> None:
        """When the git reads fail, the fields are null and the endpoint still
        responds (never hangs or raises)."""
        monkeypatch.setattr(
            "dashboard_routes._control_routes.get_boot_sha",
            lambda: None,
        )
        monkeypatch.setattr(
            "dashboard_routes._control_routes.get_commits_behind",
            lambda: None,
        )

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)

        get_control_status = find_endpoint(router, "/api/control/status")

        assert get_control_status is not None
        response = await get_control_status()
        data = json.loads(response.body)
        assert data["config"]["boot_sha"] is None
        assert data["config"]["commits_behind"] is None


class TestPatchConfigUnknownField:
    @pytest.mark.asyncio
    async def test_patch_config_ignored_field(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """Unknown fields in PATCH should be ignored without error."""

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        patch_config = find_endpoint(router, "/api/control/config")
        assert patch_config is not None

        response = await patch_config({"unknown_field": True})
        data = json.loads(response.body)
        assert data["status"] == "ok"
        assert data["updated"] == {}


class TestPatchConfigMaxTriagers:
    @pytest.mark.asyncio
    async def test_patch_config_updates_max_triagers(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        """PATCH /api/control/config with max_triagers should update config."""

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        patch_config = find_endpoint(router, "/api/control/config")
        assert patch_config is not None

        assert config.max_triagers == 1
        response = await patch_config({"max_triagers": 3})
        data = json.loads(response.body)
        assert data["status"] == "ok"
        assert data["updated"]["max_triagers"] == 3
        assert config.max_triagers == 3


class TestMergePolicyKillSwitch:
    """The CH-3 gate kill-switch must be operable at runtime (review
    finding): with a corrupt policy failing every merge seam closed, the
    System tab is the instant global-relief lever — no restart."""

    @pytest.mark.asyncio
    async def test_patches_merge_policy_enabled(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        patch_config = find_endpoint(router, "/api/control/config")
        assert patch_config is not None
        assert config.merge_policy_enabled is True
        response = await patch_config({"merge_policy_enabled": False})
        data = json.loads(response.body)
        assert data["updated"]["merge_policy_enabled"] is False
        assert config.merge_policy_enabled is False

    @pytest.mark.asyncio
    async def test_control_status_includes_merge_policy_enabled(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        get_control_status = find_endpoint(router, "/api/control/status")
        assert get_control_status is not None
        response = await get_control_status()
        data = json.loads(response.body)
        assert data["config"]["merge_policy_enabled"] is True


class TestPatchConfigStagingPromotion:
    """PATCH /api/control/config accepts the staging/RC promotion fields."""

    @pytest.mark.asyncio
    async def test_patches_staging_enabled(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        patch_config = find_endpoint(router, "/api/control/config")
        assert patch_config is not None
        response = await patch_config({"staging_enabled": True})
        data = json.loads(response.body)
        assert data["updated"]["staging_enabled"] is True
        assert config.staging_enabled is True

    @pytest.mark.asyncio
    async def test_patches_branch_names(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        patch_config = find_endpoint(router, "/api/control/config")
        assert patch_config is not None
        response = await patch_config(
            {"main_branch": "release", "staging_branch": "integration"}
        )
        data = json.loads(response.body)
        assert data["updated"]["main_branch"] == "release"
        assert data["updated"]["staging_branch"] == "integration"
        assert config.main_branch == "release"
        assert config.staging_branch == "integration"

    @pytest.mark.asyncio
    async def test_patches_rc_cadence_hours(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        patch_config = find_endpoint(router, "/api/control/config")
        assert patch_config is not None
        response = await patch_config({"rc_cadence_hours": 8})
        data = json.loads(response.body)
        assert data["updated"]["rc_cadence_hours"] == 8
        assert config.rc_cadence_hours == 8

    @pytest.mark.asyncio
    async def test_rc_cadence_hours_rejects_out_of_range(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        patch_config = find_endpoint(router, "/api/control/config")
        assert patch_config is not None
        response = await patch_config({"rc_cadence_hours": 999})
        data = json.loads(response.body)
        assert response.status_code == 422
        assert data["status"] == "error"


class TestStagingPromotionStatus:
    """GET /api/staging-promotion/status returns RC lifecycle telemetry."""

    @pytest.mark.asyncio
    async def test_reports_disabled_cleanly(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        config.staging_enabled = False
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/staging-promotion/status")
        assert endpoint is not None
        response = await endpoint()
        data = json.loads(response.body)
        assert data["enabled"] is False
        assert data["cadence_hours"] == config.rc_cadence_hours
        assert data["open_promotion_pr"] is None
        assert data["recent_promoted"] == 0
        assert data["recent_failed"] == 0
        assert data["recent_failure_rate"] is None

    @pytest.mark.asyncio
    async def test_reports_cadence_progress_from_timestamp_file(
        self, config, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        config.staging_enabled = False  # skip gh calls
        config.data_root = tmp_path / "data"
        ts_dir = config.data_root / "memory"
        ts_dir.mkdir(parents=True)
        from datetime import UTC as _UTC  # noqa: PLC0415
        from datetime import datetime as _dt  # noqa: PLC0415
        from datetime import timedelta as _td  # noqa: PLC0415

        cut = _dt.now(_UTC) - _td(hours=2, minutes=30)
        (ts_dir / ".staging_promotion_last_rc").write_text(cut.isoformat())

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/staging-promotion/status")
        assert endpoint is not None
        response = await endpoint()
        data = json.loads(response.body)
        assert data["last_rc_cut_at"] is not None
        assert 2.4 < data["cadence_progress_hours"] < 2.6


class TestPatchConfigWithRegistry:
    def _make_runtime(self, cfg, event_bus, state):
        class _StubRuntime:
            def __init__(self, config, bus, tracker):
                self.config = config
                self.event_bus = bus
                self.state = tracker
                self._orchestrator = None
                self.slug = config.repo_slug
                self._running = False

            @property
            def orchestrator(self):
                return self._orchestrator

            @property
            def running(self):
                return self._running

            async def start(self):
                self._running = True

            async def stop(self):
                self._running = False

        return _StubRuntime(cfg, event_bus, state)

    @pytest.mark.asyncio
    async def test_patch_config_updates_repo_store(
        self, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """PATCH /api/control/config with repo slug should persist overrides."""

        from repo_store import RepoRecord, RepoRegistryStore
        from state import StateTracker
        from tests.helpers import ConfigFactory

        base_cfg = ConfigFactory.create(
            repo_root=tmp_path / "base-repo",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        repo_cfg = ConfigFactory.create(
            repo="acme/widgets",
            repo_root=tmp_path / "widgets",
            workspace_base=tmp_path / "widgets-worktrees",
            state_file=tmp_path / "widgets-state.json",
        )
        runtime_state = StateTracker(repo_cfg.state_file)
        runtime = self._make_runtime(repo_cfg, event_bus, runtime_state)

        repo_store = RepoRegistryStore(tmp_path)
        repo_store.upsert(
            RepoRecord(
                slug=runtime.slug, repo=repo_cfg.repo, path=str(repo_cfg.repo_root)
            )
        )

        class _StubRegistry:
            def __init__(self, rt):
                self._runtime = rt

            def get(self, slug):
                return self._runtime if slug == self._runtime.slug else None

            @property
            def all(self):
                return [self._runtime]

            def remove(self, slug):
                return None

        router, _ = make_dashboard_router(
            base_cfg,
            event_bus,
            runtime_state,
            tmp_path,
            registry=_StubRegistry(runtime),
            default_repo_slug=runtime.slug,
            repo_store=repo_store,
        )
        patch_config = find_endpoint(router, "/api/control/config")
        assert patch_config is not None

        response = await patch_config({"max_workers": 4}, repo=runtime.slug)
        data = json.loads(response.body)
        assert data["status"] == "ok"
        assert runtime.config.max_workers == 4

        stored = repo_store.load()
        assert stored[0].overrides["max_workers"] == 4


class TestBgWorkerToggleEndpoint:
    @pytest.mark.asyncio
    async def test_bg_worker_toggle_returns_error_without_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        toggle = find_endpoint(router, "/api/control/bg-worker")
        assert toggle is not None

        response = await toggle({"name": "memory_sync", "enabled": False})
        data = json.loads(response.body)
        assert response.status_code == 400
        assert data["error"] == "no orchestrator"

    @pytest.mark.asyncio
    async def test_bg_worker_toggle_requires_name_and_enabled(
        self, config, event_bus, state, tmp_path
    ) -> None:
        mock_orch = AsyncMock()
        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        toggle = find_endpoint(router, "/api/control/bg-worker")
        assert toggle is not None

        response = await toggle({"name": "memory_sync"})
        assert response.status_code == 400

        response = await toggle({"enabled": True})
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_bg_worker_toggle_calls_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        mock_orch = MagicMock()
        mock_orch.set_bg_worker_enabled = MagicMock()
        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        toggle = find_endpoint(router, "/api/control/bg-worker")
        assert toggle is not None

        response = await toggle({"name": "memory_sync", "enabled": False})
        data = json.loads(response.body)
        assert data["status"] == "ok"
        assert data["name"] == "memory_sync"
        assert data["enabled"] is False
        mock_orch.set_bg_worker_enabled.assert_called_once_with("memory_sync", False)

    def test_route_is_registered(self, config, event_bus, state, tmp_path) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        paths = {route.path for route in router.routes if hasattr(route, "path")}
        assert "/api/control/bg-worker" in paths


# ---------------------------------------------------------------------------
# /api/control/bg-worker/restart endpoint (supervisor restart-loop action)
# ---------------------------------------------------------------------------


class TestBgWorkerRestartEndpoint:
    def test_restart_route_is_registered(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        paths = {route.path for route in router.routes if hasattr(route, "path")}
        assert "/api/control/bg-worker/restart" in paths

    @pytest.mark.asyncio
    async def test_restart_returns_error_without_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        restart = find_endpoint(router, "/api/control/bg-worker/restart")
        assert restart is not None
        response = await restart({"name": "diagram"})
        assert response.status_code == 400
        assert json.loads(response.body)["error"] == "no orchestrator"

    @pytest.mark.asyncio
    async def test_restart_requires_name(
        self, config, event_bus, state, tmp_path
    ) -> None:
        mock_orch = MagicMock()
        mock_orch.restart_loop_task = AsyncMock(return_value=True)
        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        restart = find_endpoint(router, "/api/control/bg-worker/restart")
        response = await restart({})
        assert response.status_code == 400
        mock_orch.restart_loop_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_restart_calls_orchestrator_and_reports_ok(
        self, config, event_bus, state, tmp_path
    ) -> None:
        mock_orch = MagicMock()
        mock_orch.restart_loop_task = AsyncMock(return_value=True)
        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        restart = find_endpoint(router, "/api/control/bg-worker/restart")
        response = await restart({"name": "diagram"})
        data = json.loads(response.body)
        assert response.status_code == 200
        assert data == {"status": "ok", "name": "diagram", "restarted": True}
        mock_orch.restart_loop_task.assert_awaited_once_with("diagram")

    @pytest.mark.asyncio
    async def test_restart_unknown_loop_is_404(
        self, config, event_bus, state, tmp_path
    ) -> None:
        mock_orch = MagicMock()
        mock_orch.restart_loop_task = AsyncMock(return_value=False)
        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        restart = find_endpoint(router, "/api/control/bg-worker/restart")
        response = await restart({"name": "nope"})
        assert response.status_code == 404
        assert "could not restart" in json.loads(response.body)["error"]


# ---------------------------------------------------------------------------
# /api/control/bg-worker/interval endpoint
# ---------------------------------------------------------------------------


class TestBgWorkerIntervalEndpoint:
    @pytest.fixture
    def _endpoint(self, config, event_bus, state, tmp_path):
        """Return ``(endpoint, mock_orch)`` for interval endpoint tests."""
        mock_orch = MagicMock()
        mock_orch.set_bg_worker_interval = MagicMock()
        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        ep = find_endpoint(router, "/api/control/bg-worker/interval")
        assert ep is not None
        return ep, mock_orch

    def test_interval_route_is_registered(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        paths = {route.path for route in router.routes if hasattr(route, "path")}
        assert "/api/control/bg-worker/interval" in paths

    @pytest.mark.asyncio
    async def test_interval_update_succeeds_for_pr_unsticker(self, _endpoint) -> None:
        endpoint, mock_orch = _endpoint
        response = await endpoint({"name": "pr_unsticker", "interval_seconds": 7200})
        data = json.loads(response.body)
        assert response.status_code == 200
        assert data["status"] == "ok"
        assert data["name"] == "pr_unsticker"
        assert data["interval_seconds"] == 7200
        mock_orch.set_bg_worker_interval.assert_called_once_with("pr_unsticker", 7200)

    @pytest.mark.asyncio
    async def test_interval_update_succeeds_for_metrics(self, _endpoint) -> None:
        endpoint, mock_orch = _endpoint
        response = await endpoint({"name": "metrics", "interval_seconds": 1800})
        data = json.loads(response.body)
        assert response.status_code == 200
        assert data["status"] == "ok"
        mock_orch.set_bg_worker_interval.assert_called_once_with("metrics", 1800)

    @pytest.mark.asyncio
    async def test_interval_rejects_below_minimum_for_pr_unsticker(
        self, _endpoint
    ) -> None:
        endpoint, _ = _endpoint
        response = await endpoint({"name": "pr_unsticker", "interval_seconds": 30})
        data = json.loads(response.body)
        assert response.status_code == 422
        assert "between 60 and 86400" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_rejects_above_maximum_for_pr_unsticker(
        self, _endpoint
    ) -> None:
        endpoint, _ = _endpoint
        response = await endpoint({"name": "pr_unsticker", "interval_seconds": 100000})
        data = json.loads(response.body)
        assert response.status_code == 422
        assert "between 60 and 86400" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_update_succeeds_for_pipeline_poller(
        self, _endpoint
    ) -> None:
        endpoint, mock_orch = _endpoint
        response = await endpoint({"name": "pipeline_poller", "interval_seconds": 3600})
        data = json.loads(response.body)
        assert response.status_code == 200
        assert data["status"] == "ok"
        assert data["name"] == "pipeline_poller"
        assert data["interval_seconds"] == 3600
        mock_orch.set_bg_worker_interval.assert_called_once_with(
            "pipeline_poller", 3600
        )

    @pytest.mark.asyncio
    async def test_interval_rejects_below_minimum_for_pipeline_poller(
        self, _endpoint
    ) -> None:
        endpoint, _ = _endpoint
        response = await endpoint({"name": "pipeline_poller", "interval_seconds": 2})
        data = json.loads(response.body)
        assert response.status_code == 422
        assert "between 5 and 14400" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_rejects_above_maximum_for_pipeline_poller(
        self, _endpoint
    ) -> None:
        endpoint, _ = _endpoint
        response = await endpoint(
            {"name": "pipeline_poller", "interval_seconds": 20000}
        )
        data = json.loads(response.body)
        assert response.status_code == 422
        assert "between 5 and 14400" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_rejects_non_editable_worker(self, _endpoint) -> None:
        endpoint, _ = _endpoint
        response = await endpoint({"name": "triage", "interval_seconds": 3600})
        data = json.loads(response.body)
        assert response.status_code == 400
        assert "not editable" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_rejects_missing_name(self, _endpoint) -> None:
        endpoint, _ = _endpoint
        response = await endpoint({"interval_seconds": 3600})
        data = json.loads(response.body)
        assert response.status_code == 400
        assert "required" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_rejects_missing_interval(self, _endpoint) -> None:
        endpoint, _ = _endpoint
        response = await endpoint({"name": "pr_unsticker"})
        data = json.loads(response.body)
        assert response.status_code == 400
        assert "required" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_rejects_non_integer_interval(self, _endpoint) -> None:
        endpoint, _ = _endpoint
        response = await endpoint({"name": "pr_unsticker", "interval_seconds": "abc"})
        data = json.loads(response.body)
        assert response.status_code == 400
        assert "integer" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_rejects_without_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/control/bg-worker/interval")
        assert endpoint is not None

        response = await endpoint({"name": "metrics", "interval_seconds": 3600})
        data = json.loads(response.body)
        assert response.status_code == 400
        assert data["error"] == "no orchestrator"

    @pytest.mark.asyncio
    async def test_interval_rejects_below_minimum_for_metrics(self, _endpoint) -> None:
        endpoint, _ = _endpoint
        response = await endpoint({"name": "metrics", "interval_seconds": 10})
        data = json.loads(response.body)
        assert response.status_code == 422
        assert "between 30 and 14400" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_rejects_above_maximum_for_metrics(self, _endpoint) -> None:
        endpoint, _ = _endpoint
        response = await endpoint({"name": "metrics", "interval_seconds": 20000})
        data = json.loads(response.body)
        assert response.status_code == 422
        assert "between 30 and 14400" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_update_succeeds_for_adr_reviewer(self, _endpoint) -> None:
        endpoint, mock_orch = _endpoint
        response = await endpoint({"name": "adr_reviewer", "interval_seconds": 86400})
        data = json.loads(response.body)
        assert response.status_code == 200
        assert data["status"] == "ok"
        assert data["name"] == "adr_reviewer"
        assert data["interval_seconds"] == 86400
        mock_orch.set_bg_worker_interval.assert_called_once_with("adr_reviewer", 86400)

    @pytest.mark.asyncio
    async def test_interval_rejects_below_minimum_for_adr_reviewer(
        self, _endpoint
    ) -> None:
        endpoint, _ = _endpoint
        response = await endpoint({"name": "adr_reviewer", "interval_seconds": 3600})
        data = json.loads(response.body)
        assert response.status_code == 422
        assert "between 28800 and 432000" in data["error"]

    @pytest.mark.asyncio
    async def test_interval_rejects_above_maximum_for_adr_reviewer(
        self, _endpoint
    ) -> None:
        endpoint, _ = _endpoint
        response = await endpoint({"name": "adr_reviewer", "interval_seconds": 500000})
        data = json.loads(response.body)
        assert response.status_code == 422
        assert "between 28800 and 432000" in data["error"]

    def test_interval_bounds_importable_from_module(self) -> None:
        """_INTERVAL_BOUNDS should be a module-level constant, not closure-scoped."""
        from dashboard_routes._common import _INTERVAL_BOUNDS

        assert isinstance(_INTERVAL_BOUNDS, dict)
        assert "metrics" in _INTERVAL_BOUNDS
        assert "pr_unsticker" in _INTERVAL_BOUNDS
        assert "pipeline_poller" in _INTERVAL_BOUNDS
        assert "adr_reviewer" in _INTERVAL_BOUNDS
        assert "verify_monitor" in _INTERVAL_BOUNDS
        # Each entry should be a (min, max) tuple
        for name, bounds in _INTERVAL_BOUNDS.items():
            assert isinstance(bounds, tuple), f"{name} bounds should be a tuple"
            assert len(bounds) == 2, f"{name} bounds should have 2 elements"
            assert bounds[0] < bounds[1], f"{name} min should be less than max"


# ---------------------------------------------------------------------------
# /api/control/bg-worker/watchdog-timeout endpoint (#9503)
# Mirrors TestBgWorkerIntervalEndpoint above.
# ---------------------------------------------------------------------------


class TestBgWorkerWatchdogTimeoutEndpoint:
    @pytest.fixture
    def _endpoint(self, config, event_bus, state, tmp_path):
        """Return ``(endpoint, mock_orch)`` for watchdog-timeout endpoint tests."""
        mock_orch = MagicMock()
        mock_orch.set_bg_worker_timeout = MagicMock()
        mock_orch.registered_bg_loop_names.return_value = {
            "pr_unsticker",
            "repo_wiki",
        }
        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        ep = find_endpoint(router, "/api/control/bg-worker/watchdog-timeout")
        assert ep is not None
        return ep, mock_orch

    def test_watchdog_timeout_route_is_registered(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        paths = {route.path for route in router.routes if hasattr(route, "path")}
        assert "/api/control/bg-worker/watchdog-timeout" in paths

    @pytest.mark.asyncio
    async def test_watchdog_timeout_update_succeeds(self, _endpoint) -> None:
        endpoint, mock_orch = _endpoint
        response = await endpoint(
            {"name": "pr_unsticker", "watchdog_timeout_seconds": 5400}
        )
        data = json.loads(response.body)
        assert response.status_code == 200
        assert data["status"] == "ok"
        assert data["name"] == "pr_unsticker"
        assert data["watchdog_timeout_seconds"] == 5400
        mock_orch.set_bg_worker_timeout.assert_called_once_with("pr_unsticker", 5400)

    @pytest.mark.asyncio
    async def test_watchdog_timeout_rejects_below_minimum(self, _endpoint) -> None:
        endpoint, _ = _endpoint
        response = await endpoint(
            {"name": "pr_unsticker", "watchdog_timeout_seconds": 10}
        )
        data = json.loads(response.body)
        assert response.status_code == 422
        assert "between 60 and 43200" in data["error"]

    @pytest.mark.asyncio
    async def test_watchdog_timeout_rejects_above_maximum(self, _endpoint) -> None:
        endpoint, _ = _endpoint
        response = await endpoint(
            {"name": "pr_unsticker", "watchdog_timeout_seconds": 100000}
        )
        data = json.loads(response.body)
        assert response.status_code == 422
        assert "between 60 and 43200" in data["error"]

    @pytest.mark.asyncio
    async def test_watchdog_timeout_rejects_non_loop_worker(self, _endpoint) -> None:
        endpoint, _ = _endpoint
        response = await endpoint({"name": "triage", "watchdog_timeout_seconds": 3600})
        data = json.loads(response.body)
        assert response.status_code == 400
        assert "not editable" in data["error"]

    @pytest.mark.asyncio
    async def test_watchdog_timeout_rejects_principles_audit(self, _endpoint) -> None:
        """principles_audit's cycle bound bypasses the override entirely (#9639) —
        shipping this knob for it would be a silent no-op, so it must stay
        excluded even though a loop instance is registered for it."""
        endpoint, mock_orch = _endpoint
        mock_orch.registered_bg_loop_names.return_value = {"principles_audit"}
        response = await endpoint(
            {"name": "principles_audit", "watchdog_timeout_seconds": 3600}
        )
        data = json.loads(response.body)
        assert response.status_code == 400
        assert "not editable" in data["error"]

    @pytest.mark.asyncio
    async def test_watchdog_timeout_rejects_missing_name(self, _endpoint) -> None:
        endpoint, _ = _endpoint
        response = await endpoint({"watchdog_timeout_seconds": 3600})
        data = json.loads(response.body)
        assert response.status_code == 400
        assert "required" in data["error"]

    @pytest.mark.asyncio
    async def test_watchdog_timeout_rejects_missing_timeout(self, _endpoint) -> None:
        endpoint, _ = _endpoint
        response = await endpoint({"name": "pr_unsticker"})
        data = json.loads(response.body)
        assert response.status_code == 400
        assert "required" in data["error"]

    @pytest.mark.asyncio
    async def test_watchdog_timeout_rejects_non_integer(self, _endpoint) -> None:
        endpoint, _ = _endpoint
        response = await endpoint(
            {"name": "pr_unsticker", "watchdog_timeout_seconds": "abc"}
        )
        data = json.loads(response.body)
        assert response.status_code == 400
        assert "integer" in data["error"]

    @pytest.mark.asyncio
    async def test_watchdog_timeout_rejects_without_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/control/bg-worker/watchdog-timeout")
        assert endpoint is not None

        response = await endpoint(
            {"name": "pr_unsticker", "watchdog_timeout_seconds": 3600}
        )
        data = json.loads(response.body)
        assert response.status_code == 400
        assert data["error"] == "no orchestrator"

    def test_watchdog_timeout_bounds_importable_from_module(self) -> None:
        """Mirrors test_interval_bounds_importable_from_module."""
        from dashboard_routes._common import (
            _WATCHDOG_TIMEOUT_BOUNDS,
            _WATCHDOG_TIMEOUT_EXCLUDED_WORKERS,
        )

        assert isinstance(_WATCHDOG_TIMEOUT_BOUNDS, tuple)
        assert len(_WATCHDOG_TIMEOUT_BOUNDS) == 2
        lo, hi = _WATCHDOG_TIMEOUT_BOUNDS
        assert lo < hi
        assert isinstance(_WATCHDOG_TIMEOUT_EXCLUDED_WORKERS, frozenset)
        assert "principles_audit" in _WATCHDOG_TIMEOUT_EXCLUDED_WORKERS


# ---------------------------------------------------------------------------
# /api/control/clear-credit-pause endpoint
# ---------------------------------------------------------------------------


class TestClearCreditPauseEndpoint:
    @pytest.mark.asyncio
    async def test_returns_error_without_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/control/clear-credit-pause")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert response.status_code == 400
        assert data["error"] == "no orchestrator"

    @pytest.mark.asyncio
    async def test_returns_error_when_not_paused(
        self, config, event_bus, state, tmp_path
    ) -> None:
        mock_orch = MagicMock()
        mock_orch.credits_paused_until = None
        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = find_endpoint(router, "/api/control/clear-credit-pause")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert response.status_code == 400
        assert data["error"] == "not paused"

    @pytest.mark.asyncio
    async def test_clears_pause_when_paused(
        self, config, event_bus, state, tmp_path
    ) -> None:
        from datetime import UTC, datetime, timedelta

        mock_orch = MagicMock()
        mock_orch.credits_paused_until = datetime.now(UTC) + timedelta(hours=1)
        mock_orch.clear_credit_pause = MagicMock()
        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: mock_orch
        )
        endpoint = find_endpoint(router, "/api/control/clear-credit-pause")
        assert endpoint is not None

        response = await endpoint()
        data = json.loads(response.body)
        assert response.status_code == 200
        assert data["status"] == "cleared"
        mock_orch.clear_credit_pause.assert_called_once()

    def test_route_is_registered(self, config, event_bus, state, tmp_path) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        paths = {route.path for route in router.routes if hasattr(route, "path")}
        assert "/api/control/clear-credit-pause" in paths


# ---------------------------------------------------------------------------
# /api/pipeline endpoint
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# POST /api/control/start — no-registry branch reuses the wired orchestrator
# ---------------------------------------------------------------------------


class TestStartReusesWiredOrchestrator:
    @pytest.mark.asyncio
    async def test_no_registry_start_runs_existing_orchestrator(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """The no-registry Start branch RUNS the already-wired orchestrator
        rather than constructing a fresh one with real services (#10253).

        MockWorld hands the dashboard an air-gapped fake-wired orch; the old
        branch discarded it for a brand-new ``HydraFlowOrchestrator`` built with
        real Docker/gh adapters, whose ~60 background loops wedged the shared
        event loop (the 2715s RC hang, #10215). Reusing the existing orch is
        what keeps the fake wiring alive across the Start click.
        """
        from types import SimpleNamespace

        ran = asyncio.Event()

        class _FakeOrch:
            def __init__(self) -> None:
                self.running = False
                # _runtime_status reads _svc.prs._is_fake_adapter for the status
                # route; give it a benign shape so nothing else 500s.
                self._svc = SimpleNamespace(prs=SimpleNamespace(_is_fake_adapter=True))

            async def run(self) -> None:
                ran.set()

        existing = _FakeOrch()
        captured: dict[str, object] = {}
        router, _ = make_dashboard_router(
            config,
            event_bus,
            state,
            tmp_path,
            get_orch=lambda: existing,
            set_orchestrator=lambda o: captured.__setitem__("set_orch", o),
            set_run_task=lambda t: captured.__setitem__("task", t),
            registry=None,
        )
        start = find_endpoint(router, "/api/control/start")
        assert start is not None
        response = await start()
        assert json.loads(response.body)["status"] == "started"

        # No fresh orchestrator was constructed / installed — the wiring is reused.
        assert "set_orch" not in captured
        # The scheduled run-task drives the SAME wired orch, not a new one.
        task = captured.get("task")
        assert isinstance(task, asyncio.Task)
        await task
        assert ran.is_set()

    @pytest.mark.asyncio
    async def test_no_registry_start_409_when_existing_orch_running(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """A running wired orch is never replaced — Start reports already-running."""
        from types import SimpleNamespace

        existing = SimpleNamespace(running=True)
        captured: dict[str, object] = {}
        router, _ = make_dashboard_router(
            config,
            event_bus,
            state,
            tmp_path,
            get_orch=lambda: existing,
            set_orchestrator=lambda o: captured.__setitem__("set_orch", o),
            set_run_task=lambda t: captured.__setitem__("task", t),
            registry=None,
        )
        start = find_endpoint(router, "/api/control/start")
        response = await start()
        assert response.status_code == 409
        assert "already running" in json.loads(response.body)["error"]
        assert captured == {}
