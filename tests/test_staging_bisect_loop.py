"""Tests for StagingBisectLoop (spec §4.3)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from state import StateTracker


def _make_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HydraFlowConfig:
    monkeypatch.setenv("HYDRAFLOW_STAGING_ENABLED", "true")
    monkeypatch.setenv("HYDRAFLOW_STAGING_BISECT_INTERVAL", "600")
    return HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
        data_root=tmp_path / "data",
    )


def _make_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[object, MagicMock, StateTracker]:
    from staging_bisect_loop import StagingBisectLoop

    cfg = _make_cfg(tmp_path, monkeypatch)
    stop_event = asyncio.Event()

    async def _sleep(_s: float) -> None:
        return None

    loop_deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop_event,
        status_cb=MagicMock(),
        enabled_cb=lambda _n: True,
        sleep_fn=_sleep,
    )
    prs = MagicMock()
    state = StateTracker(state_file=tmp_path / "s.json")
    loop = StagingBisectLoop(config=cfg, prs=prs, deps=loop_deps, state=state)
    return loop, prs, state


class TestSkeleton:
    @pytest.mark.asyncio
    async def test_do_work_returns_noop_when_no_red_sha(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, state = _make_loop(tmp_path, monkeypatch)
        assert state.get_last_rc_red_sha() == ""
        result = await loop._do_work()  # type: ignore[attr-defined]
        assert result == {"status": "no_red"}

    @pytest.mark.asyncio
    async def test_do_work_idempotent_on_already_processed_sha(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_rc_red_sha_and_bump_cycle("abc")
        loop._last_processed_rc_red_sha = "abc"  # type: ignore[attr-defined]
        result = await loop._do_work()  # type: ignore[attr-defined]
        assert result == {"status": "already_processed", "sha": "abc"}

    @pytest.mark.asyncio
    async def test_do_work_noop_when_staging_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)
        # _make_cfg sets STAGING_ENABLED=true; override on the constructed
        # config for this scenario (env is read at config-construct time).
        loop._config.staging_enabled = False  # type: ignore[attr-defined]
        result = await loop._do_work()  # type: ignore[attr-defined]
        assert result == {"status": "staging_disabled"}

    def test_interval_uses_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)
        assert loop._get_default_interval() == 600  # type: ignore[attr-defined]


class TestPersistence:
    @pytest.mark.asyncio
    async def test_processed_sha_persists_across_restart(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_rc_red_sha_and_bump_cycle("abc")
        # First run marks abc as seen
        await loop._do_work()  # type: ignore[attr-defined]

        # Simulate restart: create a fresh loop with the same data_root
        loop2, _prs2, _state2 = _make_loop(tmp_path, monkeypatch)
        result = await loop2._do_work()  # type: ignore[attr-defined]
        assert result["status"] == "already_processed"


class TestFlakeFilter:
    @pytest.mark.asyncio
    async def test_second_probe_passes_increments_flake_counter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_rc_red_sha_and_bump_cycle("red123")
        loop._run_bisect_probe = AsyncMock(return_value=(True, ""))  # type: ignore[attr-defined]

        result = await loop._do_work()  # type: ignore[attr-defined]

        assert result["status"] == "flake_dismissed"
        assert state.get_flake_reruns_total() == 1
        loop._run_bisect_probe.assert_awaited_once_with("red123")  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_second_probe_fails_proceeds_to_bisect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_rc_red_sha_and_bump_cycle("red456")
        loop._run_bisect_probe = AsyncMock(return_value=(False, "failing: test_foo"))  # type: ignore[attr-defined]
        loop._run_full_bisect_pipeline = AsyncMock(  # type: ignore[attr-defined]
            return_value={"status": "reverted", "pr": 99}
        )

        result = await loop._do_work()  # type: ignore[attr-defined]

        assert result["status"] == "reverted"
        assert state.get_flake_reruns_total() == 0
