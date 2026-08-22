"""Regression: composition-root ``AutoAgentRunner`` instances are air-gapped (#11602).

``build_services`` constructs three ``AutoAgentRunner`` instances at the
composition root — ``pr_red_repair_runner``, ``sandbox_failure_fixer_runner``
and ``disturbance_dampener_runner`` — and injects each into its loop. Before
this fix none of them had a fake-spawn seam:

* ``subprocess_runner=`` (the ``fake_subprocess_runner`` seam) never reaches
  them: ``BaseSubprocessRunner.run`` resolves its own runner through
  ``get_default_runner()``.
* the ``_mockworld_fake_llm`` sentinel (the ``mockworld_sentinel`` seam
  ``SANDBOX_SEAMS`` declares for ``base_subprocess_runner``) was only consulted
  by ``BaseRunner`` subclasses — ``AutoAgentRunner`` and
  ``GoalSupervisorRunner``, the module's only two subclasses, had no consult at
  all, so the declared seam covered nothing.

Any scenario seeding actionable work for one of those loops would therefore
spawn a real ``claude`` inside the air-gapped sandbox — the #9796/#11590 wedge
class (``Agent CLI authentication failed`` retries).

The fix puts the sentinel consult in ``BaseSubprocessRunner.run`` itself (one
seam covering every subclass) and attaches the sentinel to the three injected
runners in ``air_gap_runner_sentinels``.

Proof shape: #11590 patched ``AutoAgentRunner.run`` to raise and asserted it was
unreachable. Here ``run`` IS the seam, so these tests patch one level deeper —
every spawn primitive ``run`` would reach (``resolve_harness_env``,
``get_default_runner``, ``stream_claude_process``) raises, which is what "a real
subprocess" actually means. The escape raises ``BaseException`` so the runner's
never-raises contract cannot swallow it into a passing ``crashed=True``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from config import HydraFlowConfig
from events import EventBus
from mockworld.fakes import FakeGitHub, FakeLLM
from mockworld.sandbox_main import (
    _apply_sandbox_config_overrides,
    air_gap_runner_sentinels,
)
from preflight.auto_agent_runner import AutoAgentRunner
from service_registry import ServiceRegistry, WorkerRegistryCallbacks, build_services
from state import StateTracker

#: The three composition-root sites from #11602, by registry loop attribute.
SEAMED_LOOPS = [
    "pr_red_repair_loop",
    "sandbox_failure_fixer_loop",
    "disturbance_dampener_loop",
]


class _SpawnEscape(BaseException):
    """Raised when a spawn primitive is reached under the air-gap.

    Subclasses ``BaseException`` on purpose: ``BaseSubprocessRunner.run``
    collapses every ``Exception`` into ``crashed=True``, which would turn a
    breached air-gap into a green test.
    """


def _escape(*_args: Any, **_kwargs: Any) -> Any:
    raise _SpawnEscape("real subprocess spawn reached under the air-gap (#11602)")


def _recording_spawn(sink: list[str]) -> Any:
    async def _spawn(*_args: Any, **_kwargs: Any) -> str:
        sink.append("spawned")
        return ""

    return _spawn


@pytest.fixture
def forbid_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every spawn primitive ``BaseSubprocessRunner.run`` reaches explode."""
    for name in ("resolve_harness_env", "get_default_runner", "stream_claude_process"):
        monkeypatch.setattr(f"runners.base_subprocess_runner.{name}", _escape)


def _callbacks() -> WorkerRegistryCallbacks:
    return WorkerRegistryCallbacks(
        update_status=lambda *_a, **_kw: None,
        is_enabled=lambda *_a, **_kw: True,
        get_interval=lambda *_a, **_kw: 60,
        get_watchdog_timeout=lambda *_a, **_kw: 7200,
    )


def _air_gapped_registry(config: HydraFlowConfig) -> tuple[ServiceRegistry, FakeLLM]:
    """Build the real registry with a Fake PR port, then apply the shared air-gap."""
    bus = EventBus()
    svc = build_services(
        config,
        bus,
        StateTracker(config.state_file),
        asyncio.Event(),
        _callbacks(),
        prs=FakeGitHub(),
    )
    fake_llm = FakeLLM()
    air_gap_runner_sentinels(svc, fake_llm)
    return svc, fake_llm


def _runner(config: HydraFlowConfig) -> AutoAgentRunner:
    return AutoAgentRunner(config=config, event_bus=EventBus())


# ---------------------------------------------------------------------------
# The three composition-root sites
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("loop_attr", SEAMED_LOOPS)
def test_air_gap_attaches_the_sentinel_to_each_composition_root_runner(
    config: HydraFlowConfig, loop_attr: str
) -> None:
    """Each injected runner carries the fake-LLM sentinel after the air-gap."""
    svc, fake_llm = _air_gapped_registry(config)

    runner = getattr(svc, loop_attr)._runner

    assert getattr(runner, "_mockworld_fake_llm", None) is fake_llm


@pytest.mark.parametrize("loop_attr", SEAMED_LOOPS)
async def test_composition_root_runner_cannot_reach_a_real_spawn(
    config: HydraFlowConfig, loop_attr: str, forbid_spawn: None
) -> None:
    """The runner each loop actually calls is unable to spawn a subprocess."""
    svc, _fake_llm = _air_gapped_registry(config)
    runner = getattr(svc, loop_attr)._runner

    outcome = await runner.run(prompt="fix it", worktree_path="/tmp/wt", issue_number=7)

    assert outcome.crashed is True


@pytest.mark.parametrize("loop_attr", SEAMED_LOOPS)
def test_each_seamed_loop_is_wired_with_a_real_auto_agent_runner(
    config: HydraFlowConfig, loop_attr: str
) -> None:
    """Anti-vacuity: the seam is asserted against real ``AutoAgentRunner``s.

    If a loop stopped taking an injected runner (or the attribute were renamed)
    the sentinel assertions above would pass vacuously against ``None``.
    """
    svc, _fake_llm = _air_gapped_registry(config)

    assert isinstance(getattr(svc, loop_attr)._runner, AutoAgentRunner)


# ---------------------------------------------------------------------------
# The base-runner seam itself
# ---------------------------------------------------------------------------


async def test_sentinel_bypass_returns_a_crashed_outcome(
    config: HydraFlowConfig, forbid_spawn: None
) -> None:
    """A sentinel-carrying runner fails closed instead of spawning."""
    runner = _runner(config)
    vars(runner)["_mockworld_fake_llm"] = FakeLLM()

    outcome = await runner.run(prompt="p", worktree_path="/tmp/wt", issue_number=3)

    assert outcome.crashed is True


async def test_sentinel_bypass_names_the_seam_in_the_transcript(
    config: HydraFlowConfig, forbid_spawn: None
) -> None:
    """The deterministic failure explains itself to whoever reads the outcome."""
    runner = _runner(config)
    vars(runner)["_mockworld_fake_llm"] = FakeLLM()

    outcome = await runner.run(prompt="p", worktree_path="/tmp/wt", issue_number=3)

    assert "sandbox air-gap" in outcome.output_text


async def test_sentinel_bypass_is_logged(
    config: HydraFlowConfig, forbid_spawn: None, caplog: pytest.LogCaptureFixture
) -> None:
    """A skipped spawn is never silent — the sandbox operator must see it."""
    runner = _runner(config)
    vars(runner)["_mockworld_fake_llm"] = FakeLLM()

    with caplog.at_level("WARNING", logger="hydraflow.runners.base_subprocess_runner"):
        await runner.run(prompt="p", worktree_path="/tmp/wt", issue_number=3)

    assert "auto_agent_preflight" in caplog.text


async def test_non_fake_sentinel_does_not_bypass(
    config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a real Fake adapter (``_is_fake_adapter``) opens the bypass."""
    reached: list[str] = []
    monkeypatch.setattr(
        "runners.base_subprocess_runner.stream_claude_process",
        _recording_spawn(reached),
    )
    runner = _runner(config)
    vars(runner)["_mockworld_fake_llm"] = object()

    await runner.run(prompt="p", worktree_path="/tmp/wt", issue_number=3)

    assert reached == ["spawned"]


async def test_production_runner_still_reaches_the_spawn(
    config: HydraFlowConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anti-vacuity: with no sentinel attached the real spawn path still runs."""
    reached: list[str] = []
    monkeypatch.setattr(
        "runners.base_subprocess_runner.stream_claude_process",
        _recording_spawn(reached),
    )
    runner = _runner(config)

    await runner.run(prompt="p", worktree_path="/tmp/wt", issue_number=3)

    assert reached == ["spawned"]


# ---------------------------------------------------------------------------
# The fourth BaseSubprocessRunner site: built inside a method, so unattachable
# ---------------------------------------------------------------------------


def test_sandbox_pins_the_goal_supervisor_loop_off(config: HydraFlowConfig) -> None:
    """``GoalSupervisorRunner`` is built lazily inside ``_get_runner``.

    No sentinel can be attached to a runner that does not exist yet, so the
    only honest seam for that site is a config disable. The loop already ships
    default-OFF (ADR-0124) — pinning it makes the ``base_subprocess_runner``
    seam declaration true rather than aspirational, exactly as the sandbox pins
    ``rc_auto_recut_enabled``.
    """
    object.__setattr__(config, "goal_supervisor_loop_enabled", True)

    _apply_sandbox_config_overrides(config)

    assert config.goal_supervisor_loop_enabled is False
