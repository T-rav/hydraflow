"""Unit tests for src/contract_refresh_loop.py (§4.2 Phase 2 skeleton).

Covers only the Task 11/12 skeleton surface:

- construction (worker_name wired, deps stored)
- ``_get_default_interval`` reads ``config.contract_refresh_interval``
- ``_do_work`` short-circuits with ``{"status": "disabled"}`` when the
  ``enabled_cb`` kill-switch returns ``False``

Tasks 13+ (recording subroutines, drift detection, PR filing, escalation)
are out of scope for this PR and are not exercised here. Task 21 will
extend this file with the end-to-end drift scenarios; keep that split
clean by marking later tests with ``# Added in Task 21``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from contract_refresh_loop import ContractRefreshLoop

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus


def _deps(stop: asyncio.Event, *, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


def _loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    **config_overrides: object,
) -> ContractRefreshLoop:
    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        **config_overrides,
    )
    pr_manager = AsyncMock()
    state = MagicMock()
    return ContractRefreshLoop(
        config=cfg,
        prs=pr_manager,
        state=state,
        deps=_deps(asyncio.Event(), enabled=enabled),
    )


def test_loop_constructs_with_expected_worker_name(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    assert loop._worker_name == "contract_refresh"


def test_default_interval_reads_from_config(tmp_path: Path) -> None:
    # Default from the ``contract_refresh_interval`` Field (weekly cadence).
    loop = _loop(tmp_path)
    assert loop._get_default_interval() == 604800


def test_default_interval_reflects_config_override(tmp_path: Path) -> None:
    loop = _loop(tmp_path, contract_refresh_interval=86400)
    assert loop._get_default_interval() == 86400


def test_do_work_short_circuits_when_kill_switch_disabled(tmp_path: Path) -> None:
    loop = _loop(tmp_path, enabled=False)
    result = asyncio.run(loop._do_work())
    assert result == {"status": "disabled"}


def test_do_work_returns_dict_when_enabled(tmp_path: Path) -> None:
    # When enabled, the skeleton still returns a dict — Tasks 13+ will
    # expand it with adapter refresh / drift stats. The only contract
    # here is that it's a non-``disabled`` dict so the base-class status
    # reporter can publish it.
    loop = _loop(tmp_path)
    result = asyncio.run(loop._do_work())
    assert isinstance(result, dict)
    assert result.get("status") != "disabled"
