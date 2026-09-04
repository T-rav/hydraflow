"""The artifact chain survives the plan → implement hand-off (ADR-0149).

Pattern B: the plan phase's recorder and the implement phase's writer are
driven directly against a real git worktree and a real CH-1 stream. Unit
tests prove each half; this proves the hand-off — that what the plan phase
anchors is what lands, committed, on the branch the implementer will run
in, and that it lands *before* the implementer could touch it.

The git repo is real rather than faked because "the chain is committed
history the agent inherits" is the property under test, and a fake git
would let a broken commit path pass.
"""

from __future__ import annotations

import subprocess

import pytest

from change_chain import ChainArtifact, chain_dir, digest
from change_chain_gate import verify_chain
from change_chain_recorder import record_chain
from change_chain_writer import COMMIT_SUBJECT_PREFIX, ChangeChainWriter
from models import Task
from plan_phase_adversarial import CriteriaDraft
from tests.helpers import ConfigFactory

pytestmark = pytest.mark.scenario_loops


def _task(number: int = 4242) -> Task:
    return Task(
        id=number,
        title="Add the update_pr_branch port method",
        body="The unsticker needs a way to update a PR branch.",
    )


def _draft() -> CriteriaDraft:
    return CriteriaDraft(
        criteria=("update_pr_branch returns False when the merge conflicts",),
        judge_verdict="PASS",
        forwarded_concerns=(),
    )


_PLAN = "1. Add `update_pr_branch` to src/ports.py\n2. Implement in src/pr_manager.py"


@pytest.fixture
def repo(tmp_path):
    """A real git repo standing in for the issue worktree."""
    root = tmp_path / "wt"
    root.mkdir()
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@example.com"],
        ["git", "config", "user.name", "Test"],
        ["git", "commit", "-q", "--allow-empty", "-m", "root"],
    ):
        subprocess.run(cmd, cwd=root, check=True, capture_output=True)
    return root


@pytest.fixture
def config():
    return ConfigFactory.create()


async def _plan_then_implement(config, repo, *, draft=_draft()):
    """Run the recorder (plan phase) then the writer (implement phase)."""
    record = record_chain(config, _task(), _PLAN, "adds the port method", draft)
    await ChangeChainWriter(config=config).materialise(repo, 4242)
    return record


def _subjects(root) -> list[str]:
    out = subprocess.run(
        ["git", "log", "--format=%s"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.splitlines()


@pytest.mark.asyncio
async def test_all_three_plan_time_artifacts_reach_the_branch(config, repo):
    await _plan_then_implement(config, repo)

    landed = {p.name for p in chain_dir(repo, 4242).iterdir()}
    assert landed == {"intent.md", "criteria.md", "plan.md"}


@pytest.mark.asyncio
async def test_the_chain_is_committed_not_merely_written(config, repo):
    await _plan_then_implement(config, repo)

    assert _subjects(repo)[0].startswith(COMMIT_SUBJECT_PREFIX)


@pytest.mark.asyncio
async def test_the_worktree_is_clean_so_the_agent_starts_from_committed_state(
    config, repo
):
    await _plan_then_implement(config, repo)

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert status.stdout == ""


@pytest.mark.asyncio
async def test_the_landed_chain_verifies_against_its_anchor(config, repo):
    record = await _plan_then_implement(config, repo)

    findings = verify_chain(repo, 4242, record, ["src/ports.py", "src/pr_manager.py"])

    assert findings == ()


@pytest.mark.asyncio
async def test_an_agent_rewriting_the_plan_is_caught(config, repo):
    record = await _plan_then_implement(config, repo)
    (chain_dir(repo, 4242) / "plan.md").write_text("# Plan\n\nwhatever I did instead\n")

    findings = verify_chain(repo, 4242, record, ["src/ports.py"])

    assert [f.code for f in findings] == ["chain-digest-mismatch"]


@pytest.mark.asyncio
async def test_a_file_outside_the_plan_is_reported(config, repo):
    record = await _plan_then_implement(config, repo)

    findings = verify_chain(
        repo, 4242, record, ["src/ports.py", "src/something_else.py"]
    )

    assert [f.code for f in findings] == ["chain-scope-departure"]


@pytest.mark.asyncio
async def test_the_harnesses_own_chain_commit_is_not_a_scope_departure(config, repo):
    record = await _plan_then_implement(config, repo)

    findings = verify_chain(
        repo,
        4242,
        record,
        ["src/ports.py", "docs/changes/issue-4242/plan.md"],
    )

    assert findings == ()


@pytest.mark.asyncio
async def test_the_criteria_that_reach_the_branch_are_the_pre_implementation_ones(
    config, repo
):
    await _plan_then_implement(config, repo)

    body = (chain_dir(repo, 4242) / "criteria.md").read_text()
    assert "update_pr_branch returns False when the merge conflicts" in body


@pytest.mark.asyncio
async def test_the_plan_that_reaches_the_branch_matches_what_was_anchored(config, repo):
    record = await _plan_then_implement(config, repo)

    landed = (chain_dir(repo, 4242) / "plan.md").read_text()
    assert digest(landed) == record.digests[ChainArtifact.PLAN]


@pytest.mark.asyncio
async def test_a_change_planned_before_the_chain_existed_still_implements(config, repo):
    """No anchor, no chain — and no exception. The factory must not stall."""
    result = await ChangeChainWriter(config=config).materialise(repo, 9999)

    assert result.written == ()


@pytest.mark.asyncio
async def test_that_unanchored_change_is_reported_by_the_gate(config, repo):
    findings = verify_chain(repo, 9999, None, ["src/ports.py"])

    assert [f.code for f in findings] == ["chain-absent"]


@pytest.mark.asyncio
async def test_the_kill_switch_leaves_the_branch_untouched(config, repo):
    record_chain(config, _task(), _PLAN, "s", _draft())
    disabled = config.model_copy(update={"change_chain_enabled": False})

    await ChangeChainWriter(config=disabled).materialise(repo, 4242)

    assert not chain_dir(repo, 4242).exists()
