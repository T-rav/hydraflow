"""Regression #10140: HealthMonitorLoop._repo_probe delegates to an injected
RepoProber and never spawns a raw subprocess from the loop module itself.

The persistent-error self-repair actuator's ``principles_audit`` 404-prune
probes each managed repo with ``git ls-remote``. That raw ``run_subprocess_result``
spawn used to live directly in ``HealthMonitorLoop._repo_probe`` — but the
sandbox seam guard (``tests/architecture/test_sandbox_seam_completeness.py``)
only AST-scans ``src/*_loop.py`` + runners, so an undeclared spawn there wedged
the air-gapped sandbox with no seam to inject a fake into.

The fix extracts the probe into ``repo_existence_prober.DefaultRepoProber`` (a
non-``*_loop.py`` module the guard never scans) behind a ``RepoProber``
Protocol, and makes ``_repo_probe`` a thin delegate to an injected prober so the
sandbox/MockWorld inject a fake. This pins:

- ``_repo_probe`` returns exactly what the injected prober returns (True/False/
  None), forwarding the slug — i.e. it is a pure pass-through, not a spawn.
- The loop module no longer references the ``run_subprocess_result`` spawn
  primitive at all (the raw ``git ls-remote`` left ``health_monitor_loop.py``),
  while ``_check_stale_code``'s grandfathered ``run_subprocess`` fetch stays.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import health_monitor_loop
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from health_monitor_loop import HealthMonitorLoop

# ``asyncio_mode = "auto"`` (pyproject) runs the ``async def`` tests without a
# mark; a module-level ``pytest.mark.asyncio`` would wrongly tag the one sync
# test below.


def _deps() -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


class _SpyProber:
    """Records probe calls and returns a fixed verdict — no subprocess."""

    def __init__(self, verdict: bool | None) -> None:
        self._verdict = verdict
        self.calls: list[str] = []

    async def probe(self, slug: str) -> bool | None:
        self.calls.append(slug)
        return self._verdict


def _loop(tmp_path: Path, prober: _SpyProber) -> HealthMonitorLoop:
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    return HealthMonitorLoop(
        config=cfg,
        deps=_deps(),
        prs=AsyncMock(),
        repo_prober=prober,
    )


@pytest.mark.parametrize("verdict", [True, False, None])
async def test_repo_probe_is_pure_delegation(
    tmp_path: Path, verdict: bool | None
) -> None:
    prober = _SpyProber(verdict)
    loop = _loop(tmp_path, prober)
    result = await loop._repo_probe("owner/repo")
    assert result is verdict
    assert prober.calls == ["owner/repo"]


def test_loop_module_no_longer_names_the_raw_spawn_primitive() -> None:
    """The extracted probe removed ``run_subprocess_result`` from the loop
    module namespace — the s51/s56 wedge class the seam guard prevents. The
    grandfathered ``run_subprocess`` (``_check_stale_code``'s git fetch) stays.
    """
    assert not hasattr(health_monitor_loop, "run_subprocess_result")
    assert hasattr(health_monitor_loop, "run_subprocess")
