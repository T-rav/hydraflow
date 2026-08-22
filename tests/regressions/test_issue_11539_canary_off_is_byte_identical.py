"""The enforcement canary must be provably bounded and provably reversible.

#11539 (Gateway P3) is the first phase in which a routing decision changes what
gets spawned. Two properties are the whole safety case, so they are pinned here
rather than left to the feature suite:

* **Bounded.** With the canary armed for a *different* repository — or armed for
  this one but on a spawn that never reaches the gateway — the provider and the
  argv handed to the child are byte-identical to the disarmed run.
* **Reversible in one action.** Clearing ``gateway_enforcement_canary_repo``
  restores the disarmed argv exactly, with the policy snapshot left untouched on
  disk. The rollback removes the *authority*, not the rule.

The companion pin is ``test_issue_11536_shadow_route_is_inert.py``: that file
holds the route still while the resolver only observes, and this one holds
everything outside the canary still now that it can act.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import base_runner
import credit_failover
from base_runner import BaseRunner
from hydraflow_gateway.routing_policy import RoutingAction, RoutingMatch, RoutingPolicy
from hydraflow_gateway.routing_store import RoutingPolicyStore
from route_shadow import policy_snapshot_path
from runners.base_subprocess_runner import BaseSubprocessRunner, SpawnOutcome
from tests.helpers import ConfigFactory

_CANARY = "acme/project-x"
_BASELINE_MODEL = "claude-sonnet-4-6"
_POLICY_MODEL = "glm-5.3"


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # The canary policy locks to z.ai, and an account with no credential is never
    # eligible — without this every case would hold for the wrong reason.
    monkeypatch.setenv("ZAI_API_KEY", "k")
    credit_failover.reset_for_tests()
    yield
    credit_failover.reset_for_tests()


def _config(tmp_path: Path, *, canary: str, repo: str = _CANARY) -> Any:
    """A repo whose spawns already transit the gateway (``repo_provider``)."""
    config = ConfigFactory.create(repo_provider="gateway", repo_model="")
    config.data_root = tmp_path / "data"
    config.repo = repo
    config.gateway_route_shadow_enabled = False
    config.gateway_enforcement_canary_repo = canary
    return config


def _write_canary_policy(config: Any) -> None:
    """The canary's one rule: "project X always uses z.ai"."""
    RoutingPolicyStore(policy_snapshot_path(config)).save(
        [
            RoutingPolicy(
                id="project-x-zai",
                match=RoutingMatch(repo_ids=(_CANARY,)),
                action=RoutingAction(
                    provider_lock="zai-harness",
                    requirement_map=(
                        {
                            "requirement": {
                                "kind": "concrete_model",
                                "value": _BASELINE_MODEL,
                            },
                            "effective_model": _POLICY_MODEL,
                        },
                    ),
                ),
            )
        ]
    )


class _FakeResult:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


class _FakeRunner(BaseSubprocessRunner[_FakeResult]):
    """Minimal concrete seam: the base class owns the routing under test."""

    def _telemetry_source(self) -> str:
        return "canary_bound_probe"

    def _build_command(self, prompt: str, worktree: Path) -> list[str]:
        del prompt, worktree
        return ["claude", "--model", _BASELINE_MODEL, "-p"]

    def _make_result(self, outcome: SpawnOutcome) -> _FakeResult:
        return _FakeResult(crashed=outcome.crashed, transcript=outcome.transcript)


def _base_runner(config: Any) -> BaseRunner:
    runner = BaseRunner.__new__(BaseRunner)
    runner._config = config
    runner._bus = MagicMock()
    runner._bus.current_session_id = None
    runner._active_procs = set()
    runner._runner = MagicMock()
    runner._prompt_telemetry = MagicMock()
    runner._last_context_stats = {"cache_hits": 0, "cache_misses": 0}
    runner._tracing_ctx = None
    runner._credentials = MagicMock()
    runner._credentials.gh_token = ""
    runner._wiki_store = None
    runner._log = MagicMock()
    return runner


async def _agentic_route(config: Any, tmp_path: Path) -> tuple[str, list[str]]:
    """Return the ``(provider, cmd)`` ``base_runner._execute`` hands the spawn."""
    captured: dict[str, Any] = {}

    async def fake_stream(*, config: Any, **kwargs: Any) -> str:
        captured["provider"] = config.provider
        captured["cmd"] = list(kwargs["cmd"])
        return "transcript"

    with (
        patch("base_runner.stream_claude_process", side_effect=fake_stream),
        patch("base_runner.resolve_harness_env", return_value={}),
    ):
        await _base_runner(config)._execute(
            cmd=["claude", "--model", _BASELINE_MODEL, "-p"],
            prompt="p",
            cwd=tmp_path,
            event_data={"issue": 42, "source": "implementer"},
        )
    return captured["provider"], captured["cmd"]


async def _subprocess_route(config: Any, tmp_path: Path) -> tuple[str, list[str]]:
    """Return the ``(provider, cmd)`` ``BaseSubprocessRunner.run`` resolves."""
    captured: dict[str, Any] = {}

    async def fake_stream(*, config: Any, **kwargs: Any) -> str:
        captured["provider"] = config.provider
        captured["cmd"] = list(kwargs["cmd"])
        return "<status>resolved</status>"

    bus = MagicMock()
    bus.current_session_id = "test-session"
    runner = _FakeRunner(config=config, event_bus=bus)
    with (
        patch(
            "runners.base_subprocess_runner.stream_claude_process",
            side_effect=fake_stream,
        ),
        patch("runners.base_subprocess_runner.resolve_harness_env", return_value={}),
    ):
        await runner.run(prompt="x", worktree_path=str(tmp_path), issue_number=1)
    return captured["provider"], captured["cmd"]


# --------------------------------------------------------------------------
# The canary acts — so the "unchanged" assertions below are not vacuous
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_armed_canary_actually_moves_the_agentic_command(
    tmp_path: Path,
) -> None:
    """Without this, every byte-identical assertion in this file proves nothing."""
    config = _config(tmp_path, canary=_CANARY)
    _write_canary_policy(config)

    _, cmd = await _agentic_route(config, tmp_path)

    assert _POLICY_MODEL in cmd


@pytest.mark.asyncio
async def test_the_armed_canary_actually_moves_the_subprocess_command(
    tmp_path: Path,
) -> None:
    """The second agentic seam is inside the same bound, and moves with it."""
    config = _config(tmp_path, canary=_CANARY)
    _write_canary_policy(config)

    _, cmd = await _subprocess_route(config, tmp_path)

    assert _POLICY_MODEL in cmd


# --------------------------------------------------------------------------
# Reversible in one action
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clearing_the_dial_restores_the_agentic_command_exactly(
    tmp_path: Path,
) -> None:
    """One empty field, and the argv is the one the phase before this produced.

    Both runs read the SAME snapshot on disk; the only difference between them
    is the dial. Asserting that the armed argv moved first is what keeps the
    second assertion from comparing two disarmed runs.
    """
    armed = _config(tmp_path, canary=_CANARY)
    _write_canary_policy(armed)
    disarmed = _config(tmp_path, canary="")

    _, moved = await _agentic_route(armed, tmp_path)
    _, restored = await _agentic_route(disarmed, tmp_path)

    assert moved == ["claude", "--model", _POLICY_MODEL, "-p"]
    assert restored == ["claude", "--model", _BASELINE_MODEL, "-p"]


@pytest.mark.asyncio
async def test_re_arming_after_a_rollback_needs_no_new_policy(
    tmp_path: Path,
) -> None:
    """The rollback removes the authority, not the rule — nothing to re-author.

    Written as a round trip rather than as "the file still exists", because
    nothing on any path ever deletes a snapshot: the claim worth pinning is that
    the SAME snapshot governs again the moment the dial comes back.
    """
    armed = _config(tmp_path, canary=_CANARY)
    _write_canary_policy(armed)
    await _agentic_route(armed, tmp_path)
    await _agentic_route(_config(tmp_path, canary=""), tmp_path)

    _, re_armed = await _agentic_route(armed, tmp_path)

    assert re_armed == ["claude", "--model", _POLICY_MODEL, "-p"]


@pytest.mark.asyncio
async def test_clearing_the_dial_restores_the_subprocess_command_exactly(
    tmp_path: Path,
) -> None:
    """The same one action reaches both agentic seams."""
    disarmed = _config(tmp_path, canary="")
    _write_canary_policy(disarmed)

    _, cmd = await _subprocess_route(disarmed, tmp_path)

    assert cmd == ["claude", "--model", _BASELINE_MODEL, "-p"]


# --------------------------------------------------------------------------
# Bounded: everything outside the slice is byte-identical
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_canary_armed_for_another_repository_moves_nothing_here(
    tmp_path: Path,
) -> None:
    """The bound is one exact repository, and a policy alone does not widen it."""
    config = _config(tmp_path, canary="acme/somewhere-else")
    _write_canary_policy(config)

    _, cmd = await _agentic_route(config, tmp_path)

    assert cmd == ["claude", "--model", _BASELINE_MODEL, "-p"]


@pytest.mark.asyncio
async def test_a_spawn_that_never_reaches_the_gateway_is_untouched(
    tmp_path: Path,
) -> None:
    """A direct z.ai harness spawn is ungoverned traffic; the canary leaves it alone."""
    config = _config(tmp_path, canary=_CANARY)
    config.repo_provider = "zai"
    config.repo_model = "glm-5.2"
    _write_canary_policy(config)

    provider, cmd = await _agentic_route(config, tmp_path)

    assert (provider, cmd) == ("zai", ["claude", "--model", "glm-5.2", "-p"])


@pytest.mark.asyncio
async def test_an_armed_canary_with_no_policy_moves_nothing(tmp_path: Path) -> None:
    """Arming the dial on a repository that has written no rule changes nothing."""
    config = _config(tmp_path, canary=_CANARY)

    _, cmd = await _agentic_route(config, tmp_path)

    assert cmd == ["claude", "--model", _BASELINE_MODEL, "-p"]


@pytest.mark.asyncio
async def test_the_canary_never_promotes_a_spawn_onto_the_gateway(
    tmp_path: Path,
) -> None:
    """Enforcement binds what already transits the tap; it never widens the tap."""
    config = _config(tmp_path, canary=_CANARY)
    config.repo_provider = "claude"
    _write_canary_policy(config)

    provider, _ = await _agentic_route(config, tmp_path)

    assert provider == "claude"


@pytest.mark.asyncio
async def test_a_disarmed_seam_does_not_even_build_a_stage_trail(
    tmp_path: Path,
) -> None:
    """ADR-0141 §D1: the *cost* of the canary is bounded by the same field.

    Each seam checks ``canary_armed`` before it compiles the legacy stage trail
    and hands a worker thread the resolve. Deleting those four guards would leave
    every behavioural test in this file green — the predicate would still answer
    "outside" — while quietly putting four model constructions and a thread hop
    on every spawn in the fleet. This is the assertion that dies instead.
    """
    config = _config(tmp_path, canary="")
    _write_canary_policy(config)
    calls = 0
    original = base_runner.agentic_route_stages

    def counting_stages(**kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return original(**kwargs)

    with patch.object(base_runner, "agentic_route_stages", counting_stages):
        await _agentic_route(config, tmp_path)

    assert calls == 0


@pytest.mark.asyncio
async def test_an_armed_seam_does_build_one(tmp_path: Path) -> None:
    """The affirmative half: the guard skips work, it does not skip the feature."""
    config = _config(tmp_path, canary=_CANARY)
    _write_canary_policy(config)
    calls = 0
    original = base_runner.agentic_route_stages

    def counting_stages(**kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return original(**kwargs)

    with patch.object(base_runner, "agentic_route_stages", counting_stages):
        await _agentic_route(config, tmp_path)

    assert calls == 1
