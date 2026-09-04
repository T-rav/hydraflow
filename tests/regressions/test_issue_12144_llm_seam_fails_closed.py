"""#12144: the lightweight-agent seam must fail CLOSED under test.

Five loops lazily construct a real ``_CLI*`` client when no fake is injected
(``if self._x is None: self._x = _CLIAuditLLM(self._config)``). The seam failed
**open**: a test reaching the LLM path without injecting a fake spawned a real
subprocess. On a host without a working credential that surfaces as
``RuntimeError: adjudicator LLM failed (rc=1)`` or a 300s pytest timeout —
which is indistinguishable from host contention, and is how it stayed latent.

The five clients all reach the model through one chokepoint,
``run_lightweight_agent``. Guarding there covers all five, the other
lightweight-agent callers, and any loop added later — rather than five separate
patches that leave the sixth caller unprotected.
"""

from __future__ import annotations

import ast
import pathlib
from typing import TYPE_CHECKING, Any

import pytest

from execution import HostRunner, SimpleResult
from runner_utils import run_lightweight_agent
from tests.helpers import ConfigFactory

if TYPE_CHECKING:
    from collections.abc import Sequence

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"


class _Recorder:
    """Stands in for the runner and records whether it was ever reached.

    Asserting on *reach* rather than on a raised sentinel is deliberate:
    ``run_lightweight_agent`` collapses transient runner failures into a
    ``SimpleResult`` rather than propagating them, so an exception thrown from
    a fake runner is swallowed and proves nothing either way.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, _cmd: Sequence[str], **_kwargs: Any) -> SimpleResult:
        self.calls += 1
        return SimpleResult(stdout="{}", stderr="", returncode=0)


class _FakeRunner:
    """An injected fake. Not a ``HostRunner``, so the guard must let it by."""

    def __init__(self) -> None:
        self.run_simple = _Recorder()


def _host_runner_that_cannot_spawn() -> tuple[HostRunner, _Recorder]:
    """A real ``HostRunner`` whose spawn is replaced by a recorder.

    The guard keys on the runner's *type*, so this stays a genuine HostRunner
    for the isinstance check while never reaching a subprocess -- letting the
    test assert what the guard does without paying for (or depending on) a
    real model call.
    """
    runner = HostRunner()
    recorder = _Recorder()
    runner.run_simple = recorder  # type: ignore[method-assign]
    return runner, recorder


def _call(runner: object) -> Any:
    """Invoke the seam with the minimum the guard needs.

    A real config, not a mock: ``run_lightweight_agent`` serialises the config
    into prompt-observatory telemetry before it reaches the runner, and a
    ``MagicMock`` dies there with ``TypeError: not JSON serializable`` -- which
    would redden this test for a reason that has nothing to do with the guard.
    """
    return run_lightweight_agent(
        runner=runner,
        config=ConfigFactory.create(),
        tool="claude",
        model="test-model",
        prompt="hello",
        source="issue_12144_regression",
        timeout=1.0,
    )


@pytest.mark.asyncio
async def test_real_host_runner_is_refused_under_pytest() -> None:
    """The defect itself: a real runner under pytest must not reach a spawn.

    The refusal surfaces through this seam's documented soft-failure contract
    (``rc=-1`` carrying the reason) rather than as an exception, because
    ``run_lightweight_agent`` collapses backend failures by design. That is
    still loud where it matters: each loop turns a non-zero rc into
    ``RuntimeError: <role> LLM failed (rc=-1): refusing to spawn ...``.
    """
    runner, recorder = _host_runner_that_cannot_spawn()
    result = await _call(runner)
    assert result.returncode != 0
    assert "inject" in result.stderr
    assert recorder.calls == 0, "the guard must refuse BEFORE the runner is reached"


@pytest.mark.asyncio
async def test_an_injected_fake_runner_passes_the_guard() -> None:
    """The guard must not be over-broad: an injected fake still gets through."""
    fake = _FakeRunner()
    await _call(fake)
    assert fake.run_simple.calls == 1


@pytest.mark.asyncio
async def test_the_opt_in_lets_a_deliberate_live_call_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A test that genuinely wants the live path can say so explicitly."""
    monkeypatch.setenv("HYDRAFLOW_ALLOW_REAL_LLM_SPAWN", "1")
    runner, recorder = _host_runner_that_cannot_spawn()
    await _call(runner)
    assert recorder.calls == 1


def _lazily_built_llm_clients() -> list[tuple[str, str]]:
    """Every ``self._x = _CLI*(...)`` lazy-init across the loops, by AST."""
    found: list[tuple[str, str]] = []
    for path in sorted(SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            call = node.value
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
                continue
            if not call.func.id.startswith("_CLI"):
                continue
            found.append((path.name, call.func.id))
    return found


def test_the_sweep_finds_its_own_known_positives() -> None:
    """A static sweep must pass its own known positive before it is trusted.

    This is the floor both producers are registered against in
    ``tests/architecture/guard_enumeration_registry.py``: they are derived at
    import, so they cannot go stale by omission, but they CAN silently stop
    seeing their source. That failure is this test's job to catch.
    """
    clients = dict(_lazily_built_llm_clients())
    assert clients.get("sampled_audit_loop.py") is not None
    assert len(_lazily_built_llm_clients()) >= 5

    by_loop = _llm_collaborators_by_loop()
    assert ("sampled_audit", "_adjudicator") in by_loop
    assert len(by_loop) >= 5


@pytest.mark.parametrize(("module", "client"), _lazily_built_llm_clients())
def test_every_lazily_built_client_routes_through_the_guarded_seam(
    module: str, client: str
) -> None:
    """The one-chokepoint fix is only sufficient while this holds.

    A loop that builds its own client but spawns by another route would be
    unguarded. This reddens the moment someone adds one.
    """
    tree = ast.parse((SRC / module).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == client:
            body = ast.dump(node)
            assert "run_lightweight_agent" in body, (
                f"{module}::{client} builds an LLM client but does not reach "
                f"the guarded seam; the guard in run_lightweight_agent does "
                f"not protect it."
            )
            return
    pytest.fail(f"{client} not found in {module}")


def _llm_collaborators_by_loop() -> list[tuple[str, str]]:
    """(loop_name, attr) for every loop that lazily builds a real LLM client.

    Derived from ``src`` by AST rather than hand-listed. The existing wiring
    guard in ``tests/scenarios/catalog/test_collaborator_wiring.py`` has a
    hand-maintained behavioural table, which is exactly why it covered three
    of these five when #12144 was filed.
    """
    pairs: list[tuple[str, str]] = []
    for path in sorted(SRC.glob("*_loop.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            call = node.value
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
                continue
            if not call.func.id.startswith("_CLI"):
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Attribute):
                continue
            pairs.append((path.stem.removesuffix("_loop"), target.attr))
    return sorted(set(pairs))


@pytest.mark.parametrize(("loop_name", "attr"), _llm_collaborators_by_loop())
def test_catalog_never_builds_a_loop_with_a_live_spawning_llm(
    tmp_path: pathlib.Path, loop_name: str, attr: str
) -> None:
    """A scenario-built loop must never carry a ``None`` LLM collaborator.

    ``None`` is not "no LLM" — it is "construct a real one on first use". The
    existing behavioural guard seeds a port and asserts it lands, which proves
    forwarding works; it does not prove a scenario that seeds *nothing* is
    safe. This asserts the property that actually matters.
    """
    from unittest.mock import MagicMock  # noqa: PLC0415

    from tests.helpers import make_bg_loop_deps  # noqa: PLC0415
    from tests.scenarios.catalog import LoopCatalog  # noqa: PLC0415
    from tests.scenarios.catalog.loop_registrations import (  # noqa: PLC0415
        ensure_registered,
    )

    ensure_registered()
    bg = make_bg_loop_deps(tmp_path)
    instance = LoopCatalog.instantiate(
        loop_name, ports={"github": MagicMock()}, config=bg.config, deps=bg.loop_deps
    )
    assert getattr(instance, attr) is not None, (
        f"{loop_name!r} built via the catalog leaves {attr} None, so the first "
        f"use spawns a real model call mid-scenario. Give the builder a "
        f"refusing stand-in (_llm_or_refusal). See #12144."
    )
