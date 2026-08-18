"""Regression test for #11416.

``tests/scenarios/catalog/loop_registrations.py:_build_repo_wiki`` built
``RepoWikiLoop`` without its ``wiki_compiler`` collaborator, even though
``RepoWikiLoop.__init__`` accepts one (src/repo_wiki_loop.py:169). With
``self._wiki_compiler is None``, the guard at src/repo_wiki_loop.py:375
short-circuits both the legacy ``compile_topic`` branch and the tracked
``compile_topic_tracked`` branch — no MockWorld scenario run through
``world.run_with_loops(["repo_wiki"])`` could ever exercise topic
compilation (including the #11373 fingerprint gate).

Separately, ``MockWorld.__init__`` accepts a ``wiki_compiler`` ctor kwarg
(mirroring the existing ``wiki_store`` kwarg) but never landed it into
``_loop_ports``, so even a scenario that passed ``wiki_compiler=`` to the
``MockWorld`` constructor directly would still see it silently dropped.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from tests.scenarios.catalog.loop_registrations import _build_repo_wiki


def test_build_repo_wiki_wires_wiki_compiler_from_ports(tmp_path: Path) -> None:
    """The catalog builder must forward a seeded wiki_compiler port."""
    from base_background_loop import LoopDeps
    from tests.helpers import make_bg_loop_deps

    bg = make_bg_loop_deps(tmp_path)
    loop_deps = LoopDeps(
        event_bus=bg.bus,
        stop_event=bg.stop_event,
        status_cb=bg.status_cb,
        enabled_cb=bg.enabled_cb,
        sleep_fn=AsyncMock(),
    )

    sentinel_compiler = object()
    ports: dict = {"wiki_compiler": sentinel_compiler}

    loop = _build_repo_wiki(ports, bg.config, loop_deps)

    assert loop._wiki_compiler is sentinel_compiler, (
        "_build_repo_wiki did not forward the seeded wiki_compiler port to "
        "RepoWikiLoop — Phase 2/8 compilation stays unreachable in scenarios"
    )


async def test_mock_world_ctor_wiki_compiler_lands_in_loop_ports(
    tmp_path: Path,
) -> None:
    """MockWorld(..., wiki_compiler=X) must reach _loop_ports, not just
    PipelineHarness's Plan-phase wiring."""
    from tests.scenarios.fakes.mock_world import MockWorld

    sentinel_compiler = object()
    world = MockWorld(tmp_path, wiki_compiler=sentinel_compiler)

    await world.run_with_loops(["repo_wiki"], cycles=1)

    assert world._loop_ports.get("wiki_compiler") is sentinel_compiler, (
        "MockWorld's wiki_compiler ctor kwarg never reached _loop_ports — "
        "run_with_loops(['repo_wiki']) still builds a compiler-less loop"
    )
