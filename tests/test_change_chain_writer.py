"""Materialising a change's chain into its worktree (ADR-0149).

The writer is the only thing in the repo that writes ``docs/changes/``.
These tests pin that it lands the anchored bodies byte-for-byte, commits
them, and stays out of the way when there is nothing to materialise.
"""

import subprocess

import pytest

from change_chain import ChainArtifact, chain_dir, digest
from change_chain_recorder import record_chain
from change_chain_writer import COMMIT_SUBJECT_PREFIX, ChangeChainWriter
from models import Task
from plan_phase_adversarial import CriteriaDraft
from tests.helpers import ConfigFactory


def _task(number: int = 7) -> Task:
    return Task(id=number, title="Add a thing", body="Please add it.")


def _draft() -> CriteriaDraft:
    return CriteriaDraft(
        criteria=("returns 404 for an unknown id",),
        judge_verdict="PASS",
        forwarded_concerns=(),
    )


@pytest.fixture
def config():
    return ConfigFactory.create()


@pytest.fixture
def worktree(tmp_path):
    """A real git repo — the writer commits, so a fake would prove nothing."""
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
async def test_materialise_writes_the_plan_file(config, worktree):
    record_chain(config, _task(), "step one", "does a thing", None)

    await ChangeChainWriter(config=config).materialise(worktree, 7)

    assert (chain_dir(worktree, 7) / "plan.md").exists()


@pytest.mark.asyncio
async def test_materialise_writes_the_intent_file(config, worktree):
    record_chain(config, _task(), "step one", "does a thing", None)

    await ChangeChainWriter(config=config).materialise(worktree, 7)

    assert (chain_dir(worktree, 7) / "intent.md").exists()


@pytest.mark.asyncio
async def test_materialise_writes_criteria_when_the_draft_was_anchored(
    config, worktree
):
    record_chain(config, _task(), "step one", "does a thing", _draft())

    await ChangeChainWriter(config=config).materialise(worktree, 7)

    assert (chain_dir(worktree, 7) / "criteria.md").exists()


@pytest.mark.asyncio
async def test_no_criteria_file_when_no_draft_was_anchored(config, worktree):
    record_chain(config, _task(), "step one", "does a thing", None)

    await ChangeChainWriter(config=config).materialise(worktree, 7)

    assert not (chain_dir(worktree, 7) / "criteria.md").exists()


@pytest.mark.asyncio
async def test_the_written_plan_matches_its_anchored_digest(config, worktree):
    record = record_chain(config, _task(), "step one", "does a thing", None)
    assert record is not None

    await ChangeChainWriter(config=config).materialise(worktree, 7)

    written = (chain_dir(worktree, 7) / "plan.md").read_text()
    assert digest(written) == record.digests[ChainArtifact.PLAN]


@pytest.mark.asyncio
async def test_materialise_reports_what_it_wrote(config, worktree):
    record_chain(config, _task(), "step one", "does a thing", _draft())

    result = await ChangeChainWriter(config=config).materialise(worktree, 7)

    assert set(result.written) == {
        ChainArtifact.INTENT,
        ChainArtifact.PLAN,
        ChainArtifact.CRITERIA,
    }


@pytest.mark.asyncio
async def test_materialise_commits_the_chain(config, worktree):
    record_chain(config, _task(), "step one", "does a thing", None)

    result = await ChangeChainWriter(config=config).materialise(worktree, 7)

    assert result.committed is True


@pytest.mark.asyncio
async def test_the_chain_commit_is_the_most_recent_one(config, worktree):
    record_chain(config, _task(), "step one", "does a thing", None)

    await ChangeChainWriter(config=config).materialise(worktree, 7)

    assert _subjects(worktree)[0].startswith(COMMIT_SUBJECT_PREFIX)


@pytest.mark.asyncio
async def test_the_worktree_is_clean_after_materialising(config, worktree):
    record_chain(config, _task(), "step one", "does a thing", None)

    await ChangeChainWriter(config=config).materialise(worktree, 7)

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=True,
    )
    assert status.stdout == ""


@pytest.mark.asyncio
async def test_materialise_is_a_noop_when_no_record_exists(config, worktree):
    result = await ChangeChainWriter(config=config).materialise(worktree, 999)

    assert result.written == ()


@pytest.mark.asyncio
async def test_nothing_is_committed_when_there_is_no_record(config, worktree):
    await ChangeChainWriter(config=config).materialise(worktree, 999)

    assert _subjects(worktree) == ["root"]


@pytest.mark.asyncio
async def test_materialise_is_a_noop_when_the_kill_switch_is_off(worktree):
    enabled = ConfigFactory.create()
    record_chain(enabled, _task(), "step one", "does a thing", None)
    disabled = enabled.model_copy(update={"change_chain_enabled": False})

    result = await ChangeChainWriter(config=disabled).materialise(worktree, 7)

    assert result.written == ()


@pytest.mark.asyncio
async def test_a_replanned_issue_materialises_its_newest_plan(config, worktree):
    record_chain(config, _task(), "the first plan", "s", None)
    record_chain(config, _task(), "the second plan", "s", None)

    await ChangeChainWriter(config=config).materialise(worktree, 7)

    assert "the second plan" in (chain_dir(worktree, 7) / "plan.md").read_text()


@pytest.mark.asyncio
async def test_a_corrupt_stream_line_does_not_stop_materialisation(config, worktree):
    record_chain(config, _task(), "step one", "does a thing", None)
    with config.change_chain_path.open("a") as handle:
        handle.write("{not json\n")

    result = await ChangeChainWriter(config=config).materialise(worktree, 7)

    assert ChainArtifact.PLAN in result.written


@pytest.mark.asyncio
async def test_another_issues_record_is_not_materialised(config, worktree):
    record_chain(config, _task(8), "step one", "does a thing", None)

    result = await ChangeChainWriter(config=config).materialise(worktree, 7)

    assert result.written == ()
