"""MockWorld scenario: the work picker honours priority end-to-end (#10037).

The third leg of the pyramid for the selectable queue discipline.
``tests/test_queue_strategy.py`` proves the ordering engine against hand-built
``Task`` objects; ``tests/test_issue_store_queue_strategy.py`` proves the store
consults it. Neither touches the seam that actually decides whether the feature
works in production: **do the P0/P1/P2 labels survive the trip from GitHub into
``Task.tags``?**

``IssueRefinementLoop`` writes those labels to GitHub. The fetcher projects
``labels(first: 20)`` and ``GitHubIssue.to_task`` copies them into ``tags``,
where ``band_of`` reads them. If any link in that chain filtered labels down to
the pipeline-stage set, every strategy would silently degrade to FIFO with all
tests still green — the failure would be invisible until someone noticed the
factory ignoring priorities in production.

So this scenario seeds ``world.github`` (the real ``FakeGitHub``, wire-shape
``labels: [{"name": ...}]``), converts through the real ``GitHubIssue``
projection, routes into the harness's real ``IssueStore``, and asserts the
dispatch order that results — plus that draining across multiple ticks stays
correctly interleaved rather than only getting the first pick right.
"""

from __future__ import annotations

from models import GitHubIssue, Task
from queue_strategy import QueueStrategy


def _ready_label(world) -> str:
    """The implement-stage label this harness is configured with.

    Read from config rather than hardcoded: the test fixture uses
    ``test-label``, and pinning the production string here would make the
    scenario silently route nothing.
    """
    return world.harness.store._config.ready_label[0]


def _fetch_as_tasks(github, label: str) -> list[Task]:
    """Read seeded issues back out of FakeGitHub the way the fetcher does.

    ``list_issues_by_label`` returns the gh wire shape, so labels arrive as
    ``[{"name": ...}]`` and are flattened here exactly as the real fetch path
    flattens them before handing ``GitHubIssue`` to ``to_task``.
    """
    raw = github._issues.values()
    return [
        GitHubIssue(
            number=issue.number,
            title=issue.title,
            body=issue.body,
            labels=list(issue.labels),
        ).to_task()
        for issue in raw
        if issue.state == "open" and label in issue.labels
    ]


def _seed_backlog(github, ready: str) -> None:
    """An aged backlog plus fresh prioritised intake — the real-world shape.

    Numbers ascend with age (lowest = oldest), mirroring GitHub, so a FIFO
    picker would take 9001 first and a priority-aware one would not.
    """
    github.add_issue(9001, "Ancient unlabelled chore", "", labels=[ready])
    github.add_issue(9002, "Old P2 hardening", "", labels=[ready, "P2"])
    github.add_issue(9003, "Another unlabelled chore", "", labels=[ready])
    github.add_issue(9004, "Recent P1 — a loop is limping", "", labels=[ready, "P1"])
    github.add_issue(
        9005, "Newest P0 — the factory is wedged", "", labels=[ready, "P0"]
    )


class TestQueueStrategyScenario:
    """Priority labels written to GitHub actually steer what gets worked."""

    def test_priority_labels_survive_the_trip_from_github_into_task_tags(
        self, mock_world
    ) -> None:
        # The seam the other two tiers cannot see. If this regresses, every
        # strategy quietly degrades to FIFO with all unit tests still green.
        ready = _ready_label(mock_world)
        _seed_backlog(mock_world.github, ready)

        tasks = _fetch_as_tasks(mock_world.github, ready)
        by_number = {t.id: t.tags for t in tasks}

        assert "P0" in by_number[9005]
        assert "P1" in by_number[9004]
        assert "P2" in by_number[9002]
        assert by_number[9001] == [ready]

    def test_the_wedged_p0_is_worked_before_the_oldest_issue(self, mock_world) -> None:
        # The headline behaviour change: pre-#10037 this dispatched 9001.
        store = mock_world.harness.store
        ready = _ready_label(mock_world)
        store._config.queue_strategy = QueueStrategy.WEIGHTED_MIX
        _seed_backlog(mock_world.github, ready)
        store._route_issues(_fetch_as_tasks(mock_world.github, ready))

        assert [t.id for t in store.get_implementable(1)] == [9005]

    def test_draining_the_backlog_stays_interleaved_across_ticks(
        self, mock_world
    ) -> None:
        # One correct pick is not the contract — the whole drain order is.
        # P0 first, then the P1:P2:unlabelled = 3:2:1 draw. With only one P1
        # and one P2 left, the first cycle takes both plus one unlabelled,
        # and the second cycle takes the remaining unlabelled.
        store = mock_world.harness.store
        ready = _ready_label(mock_world)
        store._config.queue_strategy = QueueStrategy.WEIGHTED_MIX
        _seed_backlog(mock_world.github, ready)
        store._route_issues(_fetch_as_tasks(mock_world.github, ready))

        drained: list[int] = []
        for _ in range(5):
            picked = store.get_implementable(1)
            assert picked, "queue drained early — a task was lost"
            drained.append(picked[0].id)

        assert drained == [9005, 9004, 9002, 9001, 9003]

    def test_fifo_still_reproduces_the_pre_10037_order_end_to_end(
        self, mock_world
    ) -> None:
        # The operator escape hatch, proven at the same integration depth as
        # the new default rather than only at the unit tier.
        store = mock_world.harness.store
        ready = _ready_label(mock_world)
        store._config.queue_strategy = QueueStrategy.FIFO
        _seed_backlog(mock_world.github, ready)
        store._route_issues(_fetch_as_tasks(mock_world.github, ready))

        drained: list[int] = []
        for _ in range(5):
            picked = store.get_implementable(1)
            drained.append(picked[0].id)

        assert drained == [9001, 9002, 9003, 9004, 9005]
