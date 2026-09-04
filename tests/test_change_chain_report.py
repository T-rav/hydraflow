"""The chain gate at the merge seam (ADR-0149 P4).

Report-only is the property under test as much as the reporting is: a gate
wired into the merge path must never be able to stop a merge, and must
never raise into it.

The gate verifies the change's OWN worktree. It runs before the merge, so
the factory's main checkout has none of the PR branch — every test here
puts the chain where the writer actually put it.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from change_chain import chain_dir
from change_chain_gate import ChainFinding
from change_chain_recorder import record_chain
from change_chain_report import (
    COMMENT_HEADING,
    FINDING_UNVERIFIABLE,
    format_findings,
    report_chain_findings,
)
from models import Task
from tests.helpers import ConfigFactory

_PLAN = "## File Delta\nMODIFIED: src/a.py\nMODIFIED: src/b.py\n"


@pytest.fixture
def config():
    return ConfigFactory.create()


@pytest.fixture
def prs():
    port = MagicMock()
    port.get_pr_diff_names = AsyncMock(return_value=["src/a.py", "src/b.py"])
    port.post_pr_comment = AsyncMock()
    port.list_issue_comments = AsyncMock(return_value=[])
    return port


def _anchor_and_materialise(config, plan: str = _PLAN):
    """Anchor a chain and put it where the writer would — the issue worktree."""
    record = record_chain(config, Task(id=7, title="t", body="b"), plan, "s", None)
    directory = chain_dir(config.workspace_path_for_issue(7), 7)
    directory.mkdir(parents=True, exist_ok=True)
    for artifact, body in record.rendered.items():
        (directory / f"{artifact.value}.md").write_text(body, encoding="utf-8")
    return record


def _plan_path(config):
    return chain_dir(config.workspace_path_for_issue(7), 7) / "plan.md"


@pytest.mark.asyncio
async def test_a_matching_chain_reports_nothing(config, prs):
    _anchor_and_materialise(config)

    findings = await report_chain_findings(
        config=config, prs=prs, pr_number=99, issue_number=7
    )

    assert findings == ()


@pytest.mark.asyncio
async def test_a_clean_chain_posts_no_comment(config, prs):
    _anchor_and_materialise(config)

    await report_chain_findings(config=config, prs=prs, pr_number=99, issue_number=7)

    prs.post_pr_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_tampered_plan_is_reported(config, prs):
    _anchor_and_materialise(config)
    _plan_path(config).write_text("forged", encoding="utf-8")

    findings = await report_chain_findings(
        config=config, prs=prs, pr_number=99, issue_number=7
    )

    assert [f.code for f in findings] == ["chain-digest-mismatch"]


@pytest.mark.asyncio
async def test_the_report_goes_on_the_pull_request_not_the_issue(config, prs):
    """`post_comment` is the ISSUE method; a PR report needs post_pr_comment."""
    _anchor_and_materialise(config)
    _plan_path(config).write_text("forged", encoding="utf-8")

    await report_chain_findings(config=config, prs=prs, pr_number=99, issue_number=7)

    prs.post_pr_comment.assert_awaited_once()
    assert prs.post_pr_comment.await_args.args[0] == 99


@pytest.mark.asyncio
async def test_a_file_outside_the_plans_file_delta_is_reported(config, prs):
    _anchor_and_materialise(config)
    prs.get_pr_diff_names = AsyncMock(return_value=["src/a.py", "src/unplanned.py"])

    findings = await report_chain_findings(
        config=config, prs=prs, pr_number=99, issue_number=7
    )

    assert [f.code for f in findings] == ["chain-scope-departure"]


@pytest.mark.asyncio
async def test_a_change_with_no_anchor_is_not_reported_on(config, prs):
    """Self-maintenance PRs never went through plan; the chain skips them."""
    findings = await report_chain_findings(
        config=config, prs=prs, pr_number=99, issue_number=7
    )

    assert findings == ()
    prs.post_pr_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_empty_changed_file_list_is_unverifiable_not_clean(config, prs):
    """`gh` failing returns [], which must not read as a clean scope."""
    _anchor_and_materialise(config)
    prs.get_pr_diff_names = AsyncMock(return_value=[])

    findings = await report_chain_findings(
        config=config, prs=prs, pr_number=99, issue_number=7
    )

    assert [f.code for f in findings] == [FINDING_UNVERIFIABLE]


@pytest.mark.asyncio
async def test_an_errored_gate_is_reported_not_silent(config):
    """A gate that errored and a gate that found nothing must differ."""
    _anchor_and_materialise(config)
    port = MagicMock()
    port.get_pr_diff_names = AsyncMock(side_effect=RuntimeError("gh exploded"))
    port.post_pr_comment = AsyncMock()
    port.list_issue_comments = AsyncMock(return_value=[])

    findings = await report_chain_findings(
        config=config, prs=port, pr_number=99, issue_number=7
    )

    assert [f.code for f in findings] == [FINDING_UNVERIFIABLE]


@pytest.mark.asyncio
async def test_a_second_pass_does_not_post_a_duplicate_comment(config, prs):
    """handle_approved re-runs on retries; the report must not stack up."""
    _anchor_and_materialise(config)
    _plan_path(config).write_text("forged", encoding="utf-8")
    prs.list_issue_comments = AsyncMock(
        return_value=[{"body": f"{COMMENT_HEADING}\n\nalready here"}]
    )

    await report_chain_findings(config=config, prs=prs, pr_number=99, issue_number=7)

    prs.post_pr_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_kill_switch_stops_the_gate_entirely(prs):
    config = ConfigFactory.create().model_copy(update={"change_chain_enabled": False})

    findings = await report_chain_findings(
        config=config, prs=prs, pr_number=99, issue_number=7
    )

    assert findings == ()
    prs.get_pr_diff_names.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_comment_failure_does_not_raise_into_the_merge_path(config):
    _anchor_and_materialise(config)
    _plan_path(config).write_text("forged", encoding="utf-8")
    port = MagicMock()
    port.get_pr_diff_names = AsyncMock(return_value=["src/a.py"])
    port.list_issue_comments = AsyncMock(return_value=[])
    port.post_pr_comment = AsyncMock(side_effect=RuntimeError("gh exploded"))

    findings = await report_chain_findings(
        config=config, prs=port, pr_number=99, issue_number=7
    )

    assert [f.code for f in findings] == ["chain-digest-mismatch"]


def test_the_comment_names_the_gate_as_report_only():
    body = format_findings(7, (ChainFinding("chain-absent", "no record"),))

    assert COMMENT_HEADING in body
    assert "does not block a merge" in body


def test_the_comment_lists_every_finding():
    body = format_findings(
        7,
        (
            ChainFinding("chain-absent", "first detail"),
            ChainFinding("chain-scope-departure", "second detail"),
        ),
    )

    assert "first detail" in body
    assert "second detail" in body
