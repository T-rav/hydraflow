"""MockWorld scenario: the three composition-root auto-agent loops cannot spawn (#11602).

The regression suite proves the seam at the runner boundary. This tier proves
the integration the regression tier is blind to: each loop's REAL dispatch
method, on a registry built by the REAL composition root (``build_services``)
and air-gapped exactly as the docker sandbox and MockWorld's wired orchestrator
air-gap it (``air_gap_runner_sentinels``), reaches its injected
``AutoAgentRunner`` and comes back with a deterministic failure instead of
spawning a ``claude``.

* S1 ``sandbox_failure_fixer`` — a PR labelled ``sandbox-fail-auto-fix`` is
  polled from FakeGitHub and dispatched: ``crashed=1``, no subprocess.
* S2 ``pr_red_repair`` — a bot-authored settled-red PR is dispatched:
  ``"dispatch_crashed"``, no subprocess.
* S3 ``disturbance_dampener`` — a burn-down unit is fixed: the loop's own
  ``agent crashed`` RuntimeError, no subprocess.

Every spawn primitive ``BaseSubprocessRunner.run`` would reach raises a
``BaseException`` (not an ``Exception``, which the runner's never-raises
contract would collapse into the very ``crashed=True`` these tests assert), so
a breached air-gap fails the scenario instead of passing it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops

_AUTO_FIX_LABEL = "sandbox-fail-auto-fix"


class _SpawnEscape(BaseException):
    """Raised when a spawn primitive is reached under the air-gap."""


def _escape(*_args: Any, **_kwargs: Any) -> Any:
    raise _SpawnEscape("real subprocess spawn reached under the air-gap (#11602)")


@pytest.fixture
def forbid_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every spawn primitive ``BaseSubprocessRunner.run`` reaches explode."""
    for name in ("resolve_harness_env", "get_default_runner", "stream_claude_process"):
        monkeypatch.setattr(f"runners.base_subprocess_runner.{name}", _escape)


def _air_gapped_services(world: MockWorld, tmp_path: Path, **overrides: Any) -> Any:
    """Build the real registry over this world's fakes, then air-gap it.

    Mirrors ``MockWorld._build_wired_orchestrator`` / ``sandbox_main.main``:
    real ``build_services``, Fake ports, then the shared
    ``air_gap_runner_sentinels``.
    """
    from events import EventBus
    from mockworld.fakes import FakeLLM, FakeWorkspace
    from mockworld.sandbox_main import air_gap_runner_sentinels
    from service_registry import WorkerRegistryCallbacks, build_services
    from state import StateTracker
    from tests.helpers import ConfigFactory

    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
        **overrides,
    )
    svc = build_services(
        config,
        EventBus(),
        StateTracker(config.state_file),
        asyncio.Event(),
        WorkerRegistryCallbacks(
            update_status=lambda *_a, **_kw: None,
            is_enabled=lambda *_a, **_kw: True,
            get_interval=lambda *_a, **_kw: 60,
            get_watchdog_timeout=lambda *_a, **_kw: 7200,
        ),
        prs=world.github,
        workspaces=FakeWorkspace(config.workspace_base),
    )
    air_gap_runner_sentinels(svc, FakeLLM())
    return svc


class TestCompositionRootRunnerSeam:
    """#11602 — the latent trap, closed at every one of the three sites."""

    async def test_sandbox_failure_fixer_dispatch_cannot_spawn(
        self, tmp_path: Path, forbid_spawn: None
    ) -> None:
        """S1: the auto-fix dispatch reports a crashed attempt, not a spawn."""
        world = MockWorld(tmp_path)
        world.github.add_pr(number=42, issue_number=10, branch="agent/issue-10")
        world.github.add_pr_label(42, _AUTO_FIX_LABEL)
        svc = _air_gapped_services(world, tmp_path, sandbox_failure_fixer_enabled=True)

        result = await svc.sandbox_failure_fixer_loop._do_work()

        assert result == {
            "status": "ok",
            "candidates": 1,
            "dispatched": 0,
            "escalated": 0,
            "crashed": 1,
            "skipped_opt_out": 0,
        }

    async def test_pr_red_repair_dispatch_cannot_spawn(
        self, tmp_path: Path, forbid_spawn: None
    ) -> None:
        """S2: the Phase-2 real-red dispatch reports a crash, not a spawn."""
        world = MockWorld(tmp_path)
        world.github.add_pr(number=77, issue_number=11, branch="agent/issue-11")
        svc = _air_gapped_services(world, tmp_path)
        pr = SimpleNamespace(pr=77, branch="agent/issue-11", is_bot=True)

        status = await svc.pr_red_repair_loop._dispatch_real_red(
            pr, log_text="FAILED tests/test_thing.py::test_thing", label_cache={}
        )

        assert status == "dispatch_crashed"

    async def test_disturbance_dampener_fix_cannot_spawn(
        self, tmp_path: Path, forbid_spawn: None
    ) -> None:
        """S3: a burn-down unit fails with the loop's own crash error."""
        from disturbance.burndown import BurndownUnit

        world = MockWorld(tmp_path)
        svc = _air_gapped_services(world, tmp_path, disturbance_dampener_enabled=True)
        loop = svc.disturbance_dampener_loop
        # The real PR opener does git/gh work no scenario can do; this stand-in
        # keeps the ONE step under test — the agent generation call — intact.
        vars(loop)["_pr_opener"] = _generate_only_pr_opener
        unit = BurndownUnit(
            dimension="suppressions",
            path="src/thing.py",
            signatures=("src/thing.py::noqa:BLE001",),
            fix_prompt="Remove the suppression.",
            dedup_key="suppressions::src/thing.py",
        )

        with pytest.raises(RuntimeError, match="agent crashed"):
            await loop._fix_unit(tmp_path / "repo", unit)


async def _generate_only_pr_opener(
    *, repo_root: Path, generate: Any, **_kwargs: Any
) -> Any:
    """Run only the agent-generation step of the real PR opener's contract."""
    await generate(repo_root)
    return SimpleNamespace(status="opened")
