"""The artifact chain must never read as implementation delivery (ADR-0149).

Caught during the ADR-0149 build, by CI, after unit and scenario tests for
the chain itself were all green.

The harness commits a change's artifact chain into the worktree *before*
the implementing agent starts. Both of the factory's null-delivery defences
then saw it as the agent's work:

- ``_count_commits`` counted the chain commit, so a run that produced
  nothing reported ``commits=1`` and walked through the zero-commit gate;
- ``is_null_delivery`` saw ``docs/changes/*.md`` in the branch diff and
  classified a diagrams-only delivery as real code.

Six scenarios in ``tests/scenarios/test_agent_realistic.py`` reddened,
including ``test_A13_zero_diff_fails_without_merge`` — an agent that
delivered nothing would have merged.

The fix follows the precedent already in ``_count_commits`` for
``.beads/issues.jsonl``: factory-owned state committed before the agent
starts is not delivery. This guard pins both surfaces, because they are two
independent checks and fixing one silently leaves the other open.
"""

from __future__ import annotations

import pytest

from change_chain import ChainArtifact
from null_delivery import is_non_deliverable_path


@pytest.mark.parametrize("artifact", list(ChainArtifact))
def test_every_chain_artifact_is_non_deliverable(artifact: ChainArtifact):
    path = f"docs/changes/issue-7/{artifact.value}.md"

    assert is_non_deliverable_path(path) is True


@pytest.mark.parametrize(
    ("path", "expected", "why"),
    [
        (
            "docs/changes/archive/2026-Q3/issue-7/plan.md",
            True,
            "quarterly compaction moves the files; classification must follow",
        ),
        (
            "./docs/changes/issue-7/plan.md",
            True,
            "a leading ./ must not smuggle a chain file through",
        ),
        (
            "src/pr_manager.py",
            False,
            "the exclusion must not widen into 'nothing is delivery'",
        ),
        (
            "docs/adr/0149-the-per-change-artifact-chain.md",
            False,
            "a docs file outside the chain is still a deliverable",
        ),
        (
            "docs/changesets/thing.md",
            False,
            "docs/changesets/ is not docs/changes/",
        ),
    ],
)
def test_the_chain_prefix_classifies_neighbouring_paths_correctly(
    path: str, expected: bool, why: str
):
    assert is_non_deliverable_path(path) is expected, why


@pytest.mark.asyncio
async def test_a_chain_only_branch_counts_zero_delivery_commits(tmp_path):
    """The count itself must ignore the chain — not just the classifier.

    Behavioural, not a source grep: the two defences are independent, and a
    fix applied to only one leaves a null delivery a merge path. Driven
    against a real git repo whose ONLY commit ahead of the base touches
    docs/changes/, which is exactly the shape the harness creates before the
    agent starts.
    """
    import subprocess

    from agent._commit import AgentCommitMixin
    from execution import get_default_runner
    from tests.helpers import ConfigFactory

    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Test")
    git("commit", "-q", "--allow-empty", "-m", "base")
    git("branch", "-M", "main")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    git("checkout", "-q", "-b", "agent/issue-7")

    chain = repo / "docs" / "changes" / "issue-7"
    chain.mkdir(parents=True)
    (chain / "plan.md").write_text("a plan", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "chore(chain): artifact chain for issue #7")

    class _Host(AgentCommitMixin):
        def __init__(self) -> None:
            self._config = ConfigFactory.create()
            self._runner = get_default_runner()

    observed = await _Host()._count_commits(repo, "agent/issue-7")

    assert observed == 0, (
        f"a branch carrying only the harness's chain commit counted "
        f"{observed} delivery commit(s) — a null delivery would pass the "
        "zero-commit gate"
    )


@pytest.mark.asyncio
async def test_re_materialising_a_committed_chain_does_not_report_failure(tmp_path):
    """A resumed worktree must not look like a failed commit.

    `_setup_worktree_and_branch` calls materialise again on the resumed
    path. The files are already tracked with identical bytes, so nothing
    stages and `git commit` exits 1 with "nothing to commit". Reporting that
    as committed=False made the caller DELETE the tracked chain, and the
    agent's own `git add -A` then committed the deletions as its delivery —
    the PR shipped with the chain removed and the gate reported every
    artifact missing.
    """
    import subprocess

    from change_chain_recorder import record_chain
    from change_chain_writer import ChangeChainWriter
    from models import Task
    from tests.helpers import ConfigFactory

    config = ConfigFactory.create()
    repo = tmp_path / "wt"
    repo.mkdir()
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@example.com"],
        ["git", "config", "user.name", "Test"],
        ["git", "commit", "-q", "--allow-empty", "-m", "base"],
    ):
        subprocess.run(cmd, cwd=repo, check=True, capture_output=True)

    record_chain(config, Task(id=4242, title="t", body="b"), "a plan", "s", None)
    writer = ChangeChainWriter(config=config)
    first = await writer.materialise(repo, 4242)
    second = await writer.materialise(repo, 4242)

    assert first.committed is True
    assert second.committed is True, (
        "re-materialising an already-committed chain reported a failed "
        "commit; the caller deletes the tracked chain on that signal"
    )
