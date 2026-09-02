"""MockWorld scenario: a sensor issue that fails triage is closed, not parked.

ADR-0146 reconnected a route ADR-0118 had orphaned: an incoming system
exception that fails triage is auto-closed as a transient rather than parked
for clarification no author will ever supply. Between those two ADRs the route
had **no producer** — the only writers of its marker were unit-test fixtures —
so it stayed green while being unreachable in production.

That is precisely what a unit test cannot notice, which is why this drives the
real ``TriagePhase`` against ``FakeGitHub``: the label has to survive
``GitHubIssue.to_task`` (where it becomes a ``tag``), reach ``_flow_route``, and
close the issue through the transitioner.

The second class is the decoy. Auto-closing on a failed triage is only safe if
it fires for sensor issues and NOTHING else — the same verdict on an authored
finding must still park it, or the route silently discards human work.
"""

from __future__ import annotations

from tests.scenarios.fakes.mock_world import MockWorld

_FIND = "hydraflow-find"
_SENSOR = "bugsink"
_PARKED = "hydraflow-parked"

_TRANSIENT = (
    "## Incoming system exception\n\n"
    "| Field | Value |\n| --- | --- |\n"
    "| Type | ConnectionResetError |\n"
    "| Value | [Errno 104] Connection reset by peer |\n" + "A" * 80
)
_AUTHORED = "The board filter resets when I switch repositories.\n" + "A" * 80


def _not_ready(world: MockWorld, number: int) -> None:
    world._llm.script_triage(
        number,
        [
            {
                "ready": False,
                "clarity_score": 1,
                "needs_discovery": False,
                "reasons": ["Transient infrastructure error, not a code bug"],
            }
        ],
    )


class TestASensorIssueThatFailsTriageIsClosed:
    async def test_it_is_closed(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        world.add_issue(
            8801,
            "ConnectionResetError in worker",
            _TRANSIENT,
            labels=[_FIND, _SENSOR],
        )
        _not_ready(world, 8801)

        await world.run_pipeline()

        assert world.github.issue(8801).state == "closed", (
            "a labelled system exception that fails triage is a transient; "
            "leaving it open spends planner budget on noise"
        )

    async def test_it_is_not_parked(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        world.add_issue(
            8802,
            "ConnectionResetError in worker",
            _TRANSIENT,
            labels=[_FIND, _SENSOR],
        )
        _not_ready(world, 8802)

        await world.run_pipeline()

        assert _PARKED not in world.github.issue(8802).labels, (
            "parking waits for an author's clarification, and a sensor issue "
            "has no author to wait for"
        )


class TestAnAuthoredFindingIsStillParked:
    """The decoy: auto-close must fire for sensor issues and nothing else."""

    async def test_it_is_not_closed(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        world.add_issue(8803, "Board filter resets", _AUTHORED, labels=[_FIND])
        _not_ready(world, 8803)

        await world.run_pipeline()

        assert world.github.issue(8803).state != "closed", (
            "the same verdict on an authored finding must park it — closing "
            "would silently discard human work"
        )
