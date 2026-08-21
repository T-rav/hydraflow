"""Regression pin for #11446.

``tests/scenarios/catalog/loop_registrations.py`` defaulted the dedup port
for ``_build_erosion_metrics`` and 18 sibling builders to a bare
``MagicMock()`` with ``dedup.get.return_value = set()`` — a fixed return
value, not a stateful fake. ``add()``/``set_all()`` were no-ops against that
mock and every ``get()`` call kept returning the same empty set, so any
MockWorld scenario that ran one of these loops twice (e.g. across a cursor
reset or restart) could never observe a re-filing regression: the dedup
port looked populated to production code but never actually remembered
anything.

The fix (300b2abb) adds ``_scenario_dedup``, which builds a real
``DedupStore`` rooted at ``config.data_root/dedup/<filename>`` — mirroring
production wiring in ``src/service_registry.py`` — unless a test has
already seeded the port, and wires it into all 19 affected builders.

This file pins both the concrete symptom (erosion metrics no longer
re-files after a cursor reset when built through the catalog with an
unseeded dedup port) and the structural property (every ``*_dedup`` port
any catalog builder wires round-trips ``add()`` -> ``get()``), independent
of whether ``tests/scenarios/catalog/test_loop_instantiation.py``'s
permanent guard ever regresses or is removed.
"""

from __future__ import annotations

from pathlib import Path

from tests.scenarios.catalog.loop_registrations import _BUILDERS, ensure_registered
from tests.scenarios.test_erosion_metrics_scenario import (
    _init_repo,
    _make_state,
    _seed_scattered_symbol,
)


async def test_erosion_metrics_catalog_default_dedup_prevents_refiling_after_cursor_reset(
    tmp_path: Path,
) -> None:
    """Pins the exact symptom from the issue title: a catalog-built
    ErosionMetricsLoop's default dedup fake could not dedupe. A cursor
    reset (restart / state loss) makes the loop re-scan the same erosive
    commit range on the second tick; only dedup — not the SHA cursor —
    can prevent the duplicate filing."""
    from tests.helpers import make_bg_loop_deps
    from tests.scenarios.catalog import LoopCatalog
    from tests.scenarios.fakes.mock_world import MockWorld

    ensure_registered()

    world = MockWorld(tmp_path)
    github = world.github
    repo = _init_repo(tmp_path)
    base_sha, _erosive_sha = _seed_scattered_symbol(repo)

    state = _make_state(base_sha)

    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "repo_root", repo)
    object.__setattr__(bg.config, "erosion_metrics_loop_enabled", True)

    ports: dict = {"github": github, "erosion_metrics_state": state}
    loop = LoopCatalog.instantiate(
        "erosion_metrics", ports=ports, config=bg.config, deps=bg.loop_deps
    )

    first = await loop._do_work()
    assert first["filed"] == 1
    assert len(github._issues) == 1

    state._cursor["sha"] = base_sha  # simulate a cursor reset

    second = await loop._do_work()

    assert second["filed"] == 0, (
        "erosion_metrics_dedup did not prevent re-filing after a cursor "
        "reset — looks like the catalog is back to defaulting dedup to a "
        "MagicMock whose get() always returns a fixed value (#11446)"
    )
    assert len(github._issues) == 1  # dedup — not refiled


def test_every_scenario_catalog_dedup_port_round_trips_add_then_get(
    tmp_path: Path,
) -> None:
    """Class sweep: every ``*_dedup`` port any catalog builder wires by
    default must actually remember what was added to it. A MagicMock with
    a hardcoded ``get()`` return value passes a shallow "was a dedup port
    provided" check but silently fails this one."""
    from unittest.mock import AsyncMock, MagicMock

    from base_background_loop import LoopDeps
    from tests.helpers import make_bg_loop_deps
    from tests.scenarios.catalog import LoopCatalog

    ensure_registered()

    for name in sorted(_BUILDERS.keys()):
        bg = make_bg_loop_deps(tmp_path / name)
        loop_deps = LoopDeps(
            event_bus=bg.bus,
            stop_event=bg.stop_event,
            status_cb=bg.status_cb,
            enabled_cb=bg.enabled_cb,
            sleep_fn=AsyncMock(),
        )
        ports: dict = {
            "github": MagicMock(),
            "workspace": MagicMock(),
            "hindsight": MagicMock(),
            "sentry": MagicMock(),
            "clock": MagicMock(),
            "state": MagicMock(),
        }

        LoopCatalog.instantiate(name, ports=ports, config=bg.config, deps=loop_deps)

        for key, dedup in ports.items():
            if not key.endswith("_dedup"):
                continue
            fingerprint = f"pin-11446-{name}-{key}"
            dedup.add(fingerprint)
            assert fingerprint in dedup.get(), (
                f"{name!r} wires ports[{key!r}] to a dedup fake that "
                "doesn't round-trip add()->get() (#11446)"
            )
