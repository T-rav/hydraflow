"""The chain gate must verify the PR's worktree, not the main checkout.

Caught in review of the gate-wiring PR, after CI went green on it.

``report_chain_findings`` resolved the chain under ``config.repo_root`` —
the factory's own checkout. But the chain is committed to the PR *branch*,
and the gate runs in ``handle_approved`` BEFORE the merge, so ``repo_root``
carries none of it. ``resolve_chain_dir`` found nothing, ``verify_chain``
returned ``chain-artifact-missing`` and took its early return, and the
digest and scope checks never executed at all.

The failure shape is the dangerous one: the gate was *loud* — a finding on
every PR — while being completely blind. A reviewer skimming comments would
have seen the gate "working". Nothing in CI noticed, because every test
placed the chain wherever the code looked for it.

These tests place the chain where the WRITER puts it
(``workspace_path_for_issue``) and nowhere else, so a gate that reads any
other root finds nothing and reddens.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from change_chain import chain_dir
from change_chain_recorder import record_chain
from change_chain_report import report_chain_findings
from models import Task
from tests.helpers import ConfigFactory

_PLAN = "## File Delta\nMODIFIED: src/a.py\n"


def _port() -> MagicMock:
    port = MagicMock()
    port.get_pr_diff_names = AsyncMock(return_value=["src/a.py"])
    port.post_pr_comment = AsyncMock()
    port.list_issue_comments = AsyncMock(return_value=[])
    return port


def _materialise_into_the_worktree(config) -> None:
    """Put the chain ONLY where ChangeChainWriter puts it."""
    record = record_chain(config, Task(id=7, title="t", body="b"), _PLAN, "s", None)
    assert record is not None
    directory = chain_dir(config.workspace_path_for_issue(7), 7)
    directory.mkdir(parents=True, exist_ok=True)
    for artifact, body in record.rendered.items():
        (directory / f"{artifact.value}.md").write_text(body, encoding="utf-8")


@pytest.mark.asyncio
async def test_a_chain_in_the_prs_worktree_verifies_clean():
    config = ConfigFactory.create()
    _materialise_into_the_worktree(config)

    findings = await report_chain_findings(
        config=config, prs=_port(), pr_number=99, issue_number=7
    )

    assert findings == (), (
        "the gate did not find the chain where the writer committed it — it "
        "is reading some other checkout"
    )


@pytest.mark.asyncio
async def test_the_main_checkout_does_not_carry_the_chain_before_merge():
    """Pins the premise: repo_root is empty, so reading it can only fail."""
    config = ConfigFactory.create()
    _materialise_into_the_worktree(config)

    assert not (chain_dir(config.repo_root, 7) / "plan.md").exists()


@pytest.mark.asyncio
async def test_a_tampered_chain_is_still_caught_in_the_worktree():
    """The digest check must actually execute, not be skipped upstream.

    With the wrong root the run returned `chain-artifact-missing` and never
    reached the digest comparison, so tampering was invisible behind a
    finding that looked like a working gate.
    """
    config = ConfigFactory.create()
    _materialise_into_the_worktree(config)
    plan = chain_dir(config.workspace_path_for_issue(7), 7) / "plan.md"
    plan.write_text("forged", encoding="utf-8")

    findings = await report_chain_findings(
        config=config, prs=_port(), pr_number=99, issue_number=7
    )

    assert [f.code for f in findings] == ["chain-digest-mismatch"]


@pytest.mark.asyncio
async def test_the_scope_check_runs_rather_than_being_short_circuited():
    """Same class: a wrong root returned early and never scope-checked."""
    config = ConfigFactory.create()
    _materialise_into_the_worktree(config)
    port = _port()
    port.get_pr_diff_names = AsyncMock(return_value=["src/a.py", "src/unplanned.py"])

    findings = await report_chain_findings(
        config=config, prs=port, pr_number=99, issue_number=7
    )

    assert [f.code for f in findings] == ["chain-scope-departure"]
