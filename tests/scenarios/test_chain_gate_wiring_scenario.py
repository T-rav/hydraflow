"""The chain gate at the merge seam, through FakeGitHub (ADR-0149 P4).

Pattern B: the reporter is driven against a real ``FakeGitHub`` rather than
a bare mock, because the defects this layer exists to catch are the ones a
mock cannot see. A ``MagicMock`` answers ``post_comment`` and
``post_pr_comment`` identically; FakeGitHub does not — ``post_comment``
appends to an *issue's* comment list, ``post_pr_comment`` does not. Wiring
the PR report through the issue method passed every mock-based test in the
first cut of this file and would have shipped.
"""

from __future__ import annotations

import pytest

from change_chain import chain_dir
from change_chain_recorder import record_chain
from change_chain_report import COMMENT_HEADING, report_chain_findings
from models import Task
from tests.helpers import ConfigFactory
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops

_PLAN = "## File Delta\nMODIFIED: src/a.py\n"


def _anchor_and_materialise(config, plan: str = _PLAN):
    record = record_chain(config, Task(id=7, title="t", body="b"), plan, "s", None)
    directory = chain_dir(config.workspace_path_for_issue(7), 7)
    directory.mkdir(parents=True, exist_ok=True)
    for artifact, body in record.rendered.items():
        (directory / f"{artifact.value}.md").write_text(body, encoding="utf-8")
    return record


def _github(world: MockWorld, changed: list[str]):
    """FakeGitHub with the PR's changed-file answer scripted."""
    github = world.github

    async def _names(_pr_number: int) -> list[str]:
        return changed

    github.get_pr_diff_names = _names  # type: ignore[method-assign]
    return github


@pytest.mark.asyncio
async def test_a_clean_chain_leaves_no_comment_anywhere(tmp_path):
    config = ConfigFactory.create()
    _anchor_and_materialise(config)
    world = MockWorld(tmp_path)
    world.add_issue(7, "t", "b")
    github = _github(world, ["src/a.py"])

    findings = await report_chain_findings(
        config=config, prs=github, pr_number=99, issue_number=7
    )

    assert findings == ()
    assert not [body for _n, body in github._comments if COMMENT_HEADING in body]


@pytest.mark.asyncio
async def test_a_tampered_plan_lands_a_comment_against_the_pr_number(tmp_path):
    config = ConfigFactory.create()
    _anchor_and_materialise(config)
    (chain_dir(config.workspace_path_for_issue(7), 7) / "plan.md").write_text(
        "forged", encoding="utf-8"
    )
    world = MockWorld(tmp_path)
    world.add_issue(7, "t", "b")
    github = _github(world, ["src/a.py"])

    await report_chain_findings(config=config, prs=github, pr_number=99, issue_number=7)

    targets = [n for n, body in github._comments if COMMENT_HEADING in body]
    assert targets == [99]


@pytest.mark.asyncio
async def test_the_report_does_not_land_on_the_issues_comment_thread(tmp_path):
    """The bug a MagicMock cannot see: PR report routed to the issue."""
    config = ConfigFactory.create()
    _anchor_and_materialise(config)
    (chain_dir(config.workspace_path_for_issue(7), 7) / "plan.md").write_text(
        "forged", encoding="utf-8"
    )
    world = MockWorld(tmp_path)
    world.add_issue(7, "t", "b")
    github = _github(world, ["src/a.py"])

    await report_chain_findings(config=config, prs=github, pr_number=7, issue_number=7)

    issue_bodies = [c.body for c in github.issue(7).comments]
    assert not [body for body in issue_bodies if COMMENT_HEADING in body]


@pytest.mark.asyncio
async def test_a_change_with_no_anchor_is_left_alone(tmp_path):
    """Self-maintenance PRs never planned; the gate must not comment."""
    config = ConfigFactory.create()
    world = MockWorld(tmp_path)
    world.add_issue(7, "t", "b")
    github = _github(world, ["docs/wiki/index.md"])

    findings = await report_chain_findings(
        config=config, prs=github, pr_number=99, issue_number=7
    )

    assert findings == ()
    assert not github._comments


@pytest.mark.asyncio
async def test_a_gate_that_cannot_run_does_not_stop_the_merge(tmp_path):
    """The whole risk of wiring an observer into the merge path."""
    config = ConfigFactory.create()
    _anchor_and_materialise(config)
    world = MockWorld(tmp_path)
    world.add_issue(7, "t", "b")
    github = world.github

    async def _explodes(_pr_number: int) -> list[str]:
        raise RuntimeError("the port is down")

    github.get_pr_diff_names = _explodes  # type: ignore[method-assign]

    findings = await report_chain_findings(
        config=config, prs=github, pr_number=99, issue_number=7
    )

    assert [f.code for f in findings] == ["chain-unverifiable"]
