"""MockWorld-based scenarios for DiagramLoop (L24).

These exercise the full ``run_with_loops`` path — same harness as every other
caretaker loop — so the loop's catalog wiring, port resolution, and dispatch
are all under test, not just ``_do_work`` in isolation.

Companion to ``tests/scenarios/test_diagram_loop_scenario.py`` (which calls
``_do_work`` directly with mocked seams).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


class TestL24DiagramLoop:
    """L24: DiagramLoop regenerates docs/arch/generated/, opens PR on drift."""

    async def test_no_drift_skips_pr(self, tmp_path) -> None:
        """No arch drift → generate-in-worktree returns no-diff; no PR, no issue.

        The regen now runs inside the ephemeral worktree, so the loop routes
        through ``generate_and_open_pr_async``; a no-diff result means no PR.
        """
        world = MockWorld(tmp_path)

        _seed_ports(world, github=world.github)

        from auto_pr import AutoPrResult

        pr_helper = AsyncMock(
            return_value=AutoPrResult(
                status="no-diff", pr_url=None, branch="arch-regen-auto"
            )
        )
        with patch("auto_pr.generate_and_open_pr_async", pr_helper):
            stats = await world.run_with_loops(["diagram_loop"], cycles=1)

        assert stats["diagram_loop"] == {"drift": False}
        pr_helper.assert_awaited_once()
        assert world.github._issues == {}

    async def test_drift_opens_regen_pr_via_auto_pr(self, tmp_path) -> None:
        """Source drifted → generate_and_open_pr_async opens the regen PR."""
        world = MockWorld(tmp_path)

        _seed_ports(world, github=world.github)

        from auto_pr import AutoPrResult

        pr_helper = AsyncMock(
            return_value=AutoPrResult(
                status="opened",
                pr_url="https://github.com/x/y/pull/1",
                branch="arch-regen-auto",
            )
        )

        with (
            patch("auto_pr.generate_and_open_pr_async", pr_helper),
            # Stub _unassigned_items to focus on the PR path.
            patch(
                "diagram_loop.DiagramLoop._unassigned_items",
                AsyncMock(return_value={"loops": [], "ports": []}),
            ),
        ):
            stats = await world.run_with_loops(["diagram_loop"], cycles=1)

        result = stats["diagram_loop"]
        assert result["drift"] is True
        assert result["pr_url"] == "https://github.com/x/y/pull/1"

        pr_helper.assert_awaited_once()
        kwargs = pr_helper.await_args.kwargs
        assert kwargs["branch"] == "arch-regen-auto"
        assert "hydraflow-ready" in kwargs["labels"]
        assert kwargs["pr_title"].startswith(
            "chore(arch): regenerate architecture knowledge"
        )
        assert kwargs["path_specs"] == ["docs/arch/generated", "docs/arch/.meta.json"]
