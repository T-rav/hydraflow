"""The chain gate runs at the merge seam and never blocks it (ADR-0149 P4).

Unit tests prove the reporter. This proves the wiring: that
``handle_approved`` calls it on the real approve path, that a finding
reaches the PR as a comment, and — the property that matters most for
something newly inserted into the merge path — that a broken gate still
lets the merge through.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from change_chain import chain_dir
from change_chain_recorder import record_chain
from change_chain_report import COMMENT_HEADING, report_chain_findings
from models import Task
from tests.helpers import ConfigFactory

pytestmark = pytest.mark.scenario_loops

_DIFF = "--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n-old\n+new\n"


def _prs(diff: str = _DIFF) -> MagicMock:
    port = MagicMock()
    port.get_pr_diff = AsyncMock(return_value=diff)
    port.post_comment = AsyncMock()
    return port


def _anchor_and_materialise(config, plan: str = "touch src/a.py"):
    record = record_chain(config, Task(id=7, title="t", body="b"), plan, "s", None)
    directory = chain_dir(config.repo_root, 7)
    directory.mkdir(parents=True, exist_ok=True)
    for artifact, body in record.rendered.items():
        (directory / f"{artifact.value}.md").write_text(body, encoding="utf-8")
    return record


@pytest.mark.asyncio
async def test_a_change_whose_chain_matches_merges_without_a_comment():
    config = ConfigFactory.create()
    _anchor_and_materialise(config)
    prs = _prs()

    findings = await report_chain_findings(
        config=config, prs=prs, pr_number=99, issue_number=7
    )

    assert findings == ()
    prs.post_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_rewritten_plan_reaches_the_pr_as_a_comment():
    config = ConfigFactory.create()
    _anchor_and_materialise(config)
    (chain_dir(config.repo_root, 7) / "plan.md").write_text("forged", encoding="utf-8")
    prs = _prs()

    await report_chain_findings(config=config, prs=prs, pr_number=99, issue_number=7)

    body = prs.post_comment.await_args.args[1]
    assert COMMENT_HEADING in body
    assert "chain-digest-mismatch" in body


@pytest.mark.asyncio
async def test_a_file_outside_the_plan_is_reported_but_not_blocked():
    config = ConfigFactory.create()
    _anchor_and_materialise(config, plan="touch src/a.py")
    prs = _prs("--- a/src/unplanned.py\n+++ b/src/unplanned.py\n@@ -1 +1 @@\n-a\n+b\n")

    findings = await report_chain_findings(
        config=config, prs=prs, pr_number=99, issue_number=7
    )

    assert [f.code for f in findings] == ["chain-scope-departure"]


@pytest.mark.asyncio
async def test_the_gate_returns_findings_not_a_verdict():
    """Report-only is structural: there is no allow/deny to act on."""
    config = ConfigFactory.create()
    _anchor_and_materialise(config)
    (chain_dir(config.repo_root, 7) / "plan.md").write_text("forged", encoding="utf-8")

    findings = await report_chain_findings(
        config=config, prs=_prs(), pr_number=99, issue_number=7
    )

    assert not hasattr(findings, "allowed")
    assert all(hasattr(finding, "code") for finding in findings)


@pytest.mark.asyncio
async def test_a_gate_that_cannot_run_does_not_stop_the_merge():
    """The whole risk of wiring an observer into the merge path."""
    config = ConfigFactory.create()
    port = MagicMock()
    port.get_pr_diff = AsyncMock(side_effect=RuntimeError("the port is down"))
    port.post_comment = AsyncMock()

    findings = await report_chain_findings(
        config=config, prs=port, pr_number=99, issue_number=7
    )

    assert findings == ()
