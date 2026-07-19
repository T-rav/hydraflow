"""Scenario test fixtures."""

from __future__ import annotations

import pytest

from tests.scenarios.catalog import (
    loop_registrations as _loop_registrations,  # noqa: F401
)


@pytest.fixture(autouse=True)
def _restore_auto_pr_seams():
    """Contain the ``auto_pr`` module-global seam that some loop builders patch.

    The generate-in-worktree loop builders (``_build_corpus_learning`` /
    ``_build_contract_refresh`` in ``catalog/loop_registrations``) inject their
    stub by assigning ``auto_pr.generate_and_open_pr_async`` directly — the seam
    those loops lazily import at call time. Without a teardown the stub leaked
    past the test and a later scenario that drives the *real* helper through
    ``OpenAutoPRBotPRPort`` (e.g. ``test_edge_proposer_scenario``) saw an
    "opened" PR with zero ``gh`` calls, reddening ``make scenario-loops`` purely
    on collection order. Snapshot + restore both seams around every scenario so
    the mutation can't escape the test that made it.
    """
    import auto_pr as _auto_pr

    saved = (
        _auto_pr.generate_and_open_pr_async,
        _auto_pr.open_automated_pr_async,
    )
    try:
        yield
    finally:
        (
            _auto_pr.generate_and_open_pr_async,
            _auto_pr.open_automated_pr_async,
        ) = saved


@pytest.fixture
async def mock_world(tmp_path):
    """Provide a fresh MockWorld for scenario tests."""
    from tests.scenarios.fakes import MockWorld

    world = MockWorld(tmp_path)
    yield world
