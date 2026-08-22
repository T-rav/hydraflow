"""MockWorld scenario: phase-ordered epic children flow in order (#11614).

The live board that motivated the gate: epics #11531 (Gateway P0→P6) and
#11532 (Fable P0→P5) decomposed into 11 children, ten of which declare
``Blocked by: #N``. Nothing read those lines, so every child became eligible
at once and three implement workers would have built P3 and P6 before P0
existed — phases that touch the same subsystems, building in parallel.

This drives the real ``TriagePhase`` against ``FakeGitHub`` (the canonical
``PRPort`` fake) to pin the integration the unit tests cannot see: the gate
reads blocker state through the port, holds the child on its find label
without parking it, and lets the same child through once the blocker closes.
"""

from __future__ import annotations

from tests.scenarios.fakes.mock_world import MockWorld

_FIND = "hydraflow-find"

_P0 = "Bring up the deterministic broker with no routing changes.\n" + "A" * 80
_P1_BODY = (
    "Parent: #11531\nBlocked by: #11533\n\n"
    "## Goal\n\nAdd read-only account inventory and live route visibility.\n" + "A" * 80
)


def _world_with_ordered_pair(tmp_path, *, blocker_state: str) -> MockWorld:
    """Seed one prerequisite (#11533) and one child that declares it (#11534)."""
    world = MockWorld(tmp_path)
    # The blocker is board state, not pipeline work — seeded straight onto
    # FakeGitHub so the run below triages only the child.
    world.github.add_issue(
        11533, "Fable P0 — broker bring-up", _P0, state=blocker_state
    )
    world.add_issue(11534, "Gateway P1 — account inventory", _P1_BODY, labels=[_FIND])
    return world


class TestOpenBlockerHoldsTheChild:
    async def test_child_does_not_leave_find(self, tmp_path) -> None:
        world = _world_with_ordered_pair(tmp_path, blocker_state="open")

        await world.run_pipeline()

        assert _FIND in world.github.issue(11534).labels

    async def test_child_is_not_parked(self, tmp_path) -> None:
        world = _world_with_ordered_pair(tmp_path, blocker_state="open")

        await world.run_pipeline()

        assert "hydraflow-parked" not in world.github.issue(11534).labels

    async def test_child_is_not_commented_on_every_tick(self, tmp_path) -> None:
        world = _world_with_ordered_pair(tmp_path, blocker_state="open")

        await world.run_pipeline()

        assert [c for (target, c) in world.github._comments if target == 11534] == []

    async def test_child_never_reaches_a_pull_request(self, tmp_path) -> None:
        world = _world_with_ordered_pair(tmp_path, blocker_state="open")

        await world.run_pipeline()

        assert world.github.pr_for_issue(11534) is None


class TestClosedBlockerReleasesTheChild:
    async def test_child_advances_once_the_blocker_is_closed(self, tmp_path) -> None:
        """Self-healing: the same declaration, a closed blocker, work flows."""
        world = _world_with_ordered_pair(tmp_path, blocker_state="closed")

        await world.run_pipeline()

        assert _FIND not in world.github.issue(11534).labels
