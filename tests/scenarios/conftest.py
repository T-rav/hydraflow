"""Scenario test fixtures."""

from __future__ import annotations

import pytest

from tests.scenarios.catalog import (
    loop_registrations as _loop_registrations,  # noqa: F401
)


@pytest.fixture(autouse=True)
def _restore_loop_catalog_registry():
    """Keep the process-global ``LoopCatalog`` registry populated across the tree.

    ``catalog/test_loop_catalog.py`` wipes ``LoopCatalog._registry`` in its own
    autouse teardown and never repopulates it; because ``loop_registrations`` is
    cached in ``sys.modules`` a re-import does not re-run ``ensure_registered()``.
    So a later scenario file on the same xdist worker that calls
    ``run_with_loops`` hits ``KeyError: Unknown loop`` (registry empty) — the
    scheduling-dependent flake that kept ``tests/scenarios`` out of the parallel
    lane (#10111). Repopulate + snapshot on setup and restore on teardown, around
    every scenario, so no test can leave the registry empty for the next.
    Mirrors ``_restore_auto_pr_seams`` (now repo-wide in ``tests/conftest.py``
    — #10433 CI investigation: the scenario-scoped version didn't protect
    non-scenario modules like ``tests/test_auto_pr_preflight.py`` from a
    leaked stub under xdist cross-module scheduling).
    """
    from tests.scenarios.catalog.loop_catalog import LoopCatalog

    _loop_registrations.ensure_registered()
    snapshot = dict(LoopCatalog._registry)
    try:
        yield
    finally:
        LoopCatalog._registry = snapshot


@pytest.fixture
async def mock_world(tmp_path):
    """Provide a fresh MockWorld for scenario tests."""
    from tests.scenarios.fakes import MockWorld

    world = MockWorld(tmp_path)
    yield world
