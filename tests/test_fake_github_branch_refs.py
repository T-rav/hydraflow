"""FakeGitHub branch-ref lifecycle state (#11227).

``FakeGitHub`` previously modeled PRs (``FakePR``) but had no branch-ref
state: ``push_branch`` was a no-op, ``delete_branch`` only popped the
RC-specific ``_rc_branches`` map, and ``merge_pr`` never emulated GitHub's
delete-branch-on-merge. Any loop/phase behaviour keyed on "does the head ref
still exist" (post-merge orphan detection, branch GC, PR recreation) had no
observable surface at the MockWorld tier.

These tests pin the new ``_branch_tips`` ref map — the fake's single source
of truth for ref existence — plus the seed/inspect helpers and the
``_run_gh`` branch reads ``StaleIssueLoop``'s branch-GC reconciler composes.
"""

from __future__ import annotations

import json

import pytest

from mockworld.fakes import FakeGitHub
from mockworld.seed import MockWorldSeed

# ---------------------------------------------------------------------------
# P1 — Branch-ref state + seed/inspect API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seeded_branch_reports_tip_sha() -> None:
    gh = FakeGitHub()
    gh.seed_branch("agent/issue-42", sha="deadbeef")

    assert gh.branch_tip("agent/issue-42") == "deadbeef"


@pytest.mark.asyncio
async def test_seed_branch_defaults_sha_deterministically() -> None:
    gh = FakeGitHub()
    gh.seed_branch("agent/issue-42")

    assert gh.branch_tip("agent/issue-42") == "sha-agent/issue-42"


def test_unseeded_branch_reports_none() -> None:
    gh = FakeGitHub()

    assert gh.branch_tip("never-pushed") is None


def test_branch_tips_returns_defensive_copy() -> None:
    gh = FakeGitHub()
    gh.seed_branch("agent/issue-42", sha="deadbeef")

    tips = gh.branch_tips()
    tips["injected"] = "should-not-appear"

    assert "injected" not in gh.branch_tips()
    assert gh.branch_tips() == {"agent/issue-42": "deadbeef"}


def test_fresh_fake_reports_no_branch_tips() -> None:
    gh = FakeGitHub()

    assert gh.branch_tips() == {}


# ---------------------------------------------------------------------------
# P2 — Lifecycle wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_branch_makes_tip_observable() -> None:
    gh = FakeGitHub()

    ok = await gh.push_branch("/tmp/wt", "feat/push-me")

    assert ok is True
    assert gh.branch_tip("feat/push-me") is not None


@pytest.mark.asyncio
async def test_repushing_branch_keeps_same_sha() -> None:
    gh = FakeGitHub()
    await gh.push_branch("/tmp/wt", "feat/stable")
    first = gh.branch_tip("feat/stable")

    await gh.push_branch("/tmp/wt", "feat/stable")

    assert gh.branch_tip("feat/stable") == first


@pytest.mark.asyncio
async def test_force_push_yields_different_sha() -> None:
    gh = FakeGitHub()
    await gh.push_branch("/tmp/wt", "feat/rewrite")
    before = gh.branch_tip("feat/rewrite")

    await gh.push_branch("/tmp/wt", "feat/rewrite", force=True)

    after = gh.branch_tip("feat/rewrite")
    assert after != before
    assert after is not None


@pytest.mark.asyncio
async def test_delete_branch_removes_tracked_tip_and_returns_true() -> None:
    gh = FakeGitHub()
    await gh.push_branch("/tmp/wt", "feat/gone")

    result = await gh.delete_branch("feat/gone")

    assert result is True
    assert gh.branch_tip("feat/gone") is None


@pytest.mark.asyncio
async def test_delete_branch_untracked_returns_false_and_leaves_state_unchanged() -> (
    None
):
    gh = FakeGitHub()
    await gh.push_branch("/tmp/wt", "feat/keep")

    result = await gh.delete_branch("feat/never-existed")

    assert result is False
    assert gh.branch_tip("feat/keep") is not None
    assert gh.branch_tips() == {"feat/keep": gh.branch_tip("feat/keep")}


@pytest.mark.asyncio
async def test_create_rc_branch_makes_tip_observable() -> None:
    gh = FakeGitHub()

    sha = await gh.create_rc_branch("rc/2026-07-22-0400")

    assert gh.branch_tip("rc/2026-07-22-0400") == sha


@pytest.mark.asyncio
async def test_push_synthetic_commit_advances_tip() -> None:
    gh = FakeGitHub()
    await gh.create_rc_branch("rc/2026-07-22-0400")
    before = gh.branch_tip("rc/2026-07-22-0400")

    new_sha = await gh.push_synthetic_commit("rc/2026-07-22-0400", "chore: sync")

    after = gh.branch_tip("rc/2026-07-22-0400")
    assert after == new_sha
    assert after != before


@pytest.mark.asyncio
async def test_create_pr_records_a_tip_for_its_branch() -> None:
    gh = FakeGitHub()
    from tests.conftest import IssueFactory  # noqa: PLC0415

    issue = IssueFactory.create(number=10)

    await gh.create_pr(issue, branch="agent/issue-10")

    assert gh.branch_tip("agent/issue-10") is not None


@pytest.mark.asyncio
async def test_create_pr_does_not_clobber_an_existing_tip() -> None:
    gh = FakeGitHub()
    from tests.conftest import IssueFactory  # noqa: PLC0415

    issue = IssueFactory.create(number=10)
    await gh.push_branch("/tmp/wt", "agent/issue-10", force=True)
    pushed_tip = gh.branch_tip("agent/issue-10")

    await gh.create_pr(issue, branch="agent/issue-10")

    assert gh.branch_tip("agent/issue-10") == pushed_tip


@pytest.mark.asyncio
async def test_ensure_branch_exists_records_a_tip_but_still_reports_false() -> None:
    """Models the steady state (branch already present): the fake always
    returns False, but the branch is guaranteed to exist afterward — so a
    missing tip is created as a side effect of calling this method."""
    gh = FakeGitHub()

    created = await gh.ensure_branch_exists("staging", base="main")

    assert created is False
    assert gh.branch_tip("staging") is not None


@pytest.mark.asyncio
async def test_get_pr_head_sha_follows_branch_tip_once_tracked() -> None:
    gh = FakeGitHub()
    gh.add_pr(number=1, issue_number=10, branch="agent/issue-10")
    await gh.push_branch("/tmp/wt", "agent/issue-10")

    sha = await gh.get_pr_head_sha(1)

    assert sha == gh.branch_tip("agent/issue-10")


@pytest.mark.asyncio
async def test_get_pr_head_sha_falls_back_to_legacy_default_when_untracked() -> None:
    gh = FakeGitHub()
    gh.add_pr(number=1, issue_number=10, branch="agent/issue-10")

    sha = await gh.get_pr_head_sha(1)

    assert sha == "abc123"


# ---------------------------------------------------------------------------
# P3 — Delete-branch-on-merge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_pr_records_tip_sha_at_merge_time() -> None:
    gh = FakeGitHub()
    gh.add_pr(number=1, issue_number=10, branch="agent/issue-10")
    await gh.push_branch("/tmp/wt", "agent/issue-10")
    tip_before_merge = gh.branch_tip("agent/issue-10")

    await gh.merge_pr(1)

    assert gh.pr(1).merged_head_sha == tip_before_merge


@pytest.mark.asyncio
async def test_merge_pr_removes_branch_tip() -> None:
    gh = FakeGitHub()
    gh.add_pr(number=1, issue_number=10, branch="agent/issue-10")
    await gh.push_branch("/tmp/wt", "agent/issue-10")

    await gh.merge_pr(1)

    assert gh.branch_tip("agent/issue-10") is None


@pytest.mark.asyncio
async def test_merge_promotion_pr_removes_rc_tip_and_drops_from_listing() -> None:
    gh = FakeGitHub()
    await gh.create_rc_branch("rc/2026-07-22-0400")
    pr_number = await gh.create_promotion_pr(
        rc_branch="rc/2026-07-22-0400", title="Promote", body="b"
    )

    await gh.merge_promotion_pr(pr_number)

    assert gh.branch_tip("rc/2026-07-22-0400") is None
    assert await gh.list_rc_branches() == []


@pytest.mark.asyncio
async def test_merge_pr_branch_never_pushed_still_succeeds_no_sha_recorded() -> None:
    gh = FakeGitHub()
    gh.add_pr(number=1, issue_number=10, branch="agent/issue-10")

    merged = await gh.merge_pr(1)

    assert merged is True
    assert gh.pr(1).merged_head_sha == ""


# ---------------------------------------------------------------------------
# P4 — Branch reads through _run_gh + seed threading
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matching_refs_returns_only_tracked_branches_under_prefix() -> None:
    gh = FakeGitHub()
    gh._repo = "owner/repo"
    gh.seed_branch("agent/issue-1")
    gh.seed_branch("agent/issue-2")
    gh.seed_branch("fix/other-thing")

    raw = await gh._run_gh(
        "gh",
        "api",
        "repos/owner/repo/git/matching-refs/heads/agent/issue-",
        "--jq",
        "[.[].ref]",
    )

    refs = json.loads(raw)
    assert sorted(refs) == ["refs/heads/agent/issue-1", "refs/heads/agent/issue-2"]


@pytest.mark.asyncio
async def test_deleted_branch_disappears_from_next_matching_refs_read() -> None:
    gh = FakeGitHub()
    gh._repo = "owner/repo"
    gh.seed_branch("agent/issue-1")
    await gh.delete_branch("agent/issue-1")

    raw = await gh._run_gh(
        "gh",
        "api",
        "repos/owner/repo/git/matching-refs/heads/agent/issue-",
        "--jq",
        "[.[].ref]",
    )

    assert json.loads(raw) == []


@pytest.mark.asyncio
async def test_commits_read_returns_seeded_date_and_messages() -> None:
    gh = FakeGitHub()
    gh._repo = "owner/repo"
    gh.seed_branch(
        "agent/issue-1",
        last_commit_at="2026-05-01T00:00:00Z",
        commit_messages=["Fixes #1: do the thing", "wip"],
    )

    raw = await gh._run_gh(
        "gh",
        "api",
        "repos/owner/repo/commits",
        "--method",
        "GET",
        "--field",
        "sha=agent/issue-1",
        "--field",
        "per_page=30",
        "--jq",
        "[.[] | {date: .commit.committer.date, message: .commit.message}]",
    )

    commits = json.loads(raw)
    assert commits[0] == {
        "date": "2026-05-01T00:00:00Z",
        "message": "Fixes #1: do the thing",
    }
    assert [c["message"] for c in commits] == ["Fixes #1: do the thing", "wip"]


@pytest.mark.asyncio
async def test_commits_read_unknown_branch_returns_empty() -> None:
    gh = FakeGitHub()
    gh._repo = "owner/repo"

    raw = await gh._run_gh(
        "gh",
        "api",
        "repos/owner/repo/commits",
        "--method",
        "GET",
        "--field",
        "sha=never-seeded",
        "--field",
        "per_page=30",
        "--jq",
        "[.[] | {date: .commit.committer.date, message: .commit.message}]",
    )

    assert json.loads(raw) == []


def test_seed_with_branches_populates_tips_via_from_seed() -> None:
    seed = MockWorldSeed(
        branches=[
            {
                "branch": "agent/issue-77",
                "sha": "cafef00d",
                "last_commit_at": "2026-05-01T00:00:00Z",
                "commit_messages": ["Fixes #77"],
            }
        ]
    )

    gh = FakeGitHub.from_seed(seed)

    assert gh.branch_tip("agent/issue-77") == "cafef00d"


def test_seed_with_branches_omitted_is_a_no_op() -> None:
    seed = MockWorldSeed()

    gh = FakeGitHub.from_seed(seed)

    assert gh.branch_tips() == {}


def test_seed_with_branches_populates_tips_via_mock_world_apply_seed(tmp_path) -> None:
    from tests.scenarios.fakes.mock_world import MockWorld

    seed = MockWorldSeed(branches=[{"branch": "agent/issue-88", "sha": "beefcafe"}])

    world = MockWorld(tmp_path).apply_seed(seed)

    assert world.github.branch_tip("agent/issue-88") == "beefcafe"
