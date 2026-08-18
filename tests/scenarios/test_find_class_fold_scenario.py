"""MockWorld scenario for the class-key fold layer (#11292).

Exercises ``find_class_key.file_or_fold`` against a real ``FakeGitHub`` port
(no subprocess, no real ``gh``) — the integration tier unit tests can't see:
a class-level issue created through the real ``create_issue`` path, then a
later-tick sibling site folded through the real ``list_issues_by_label`` +
``update_issue_body`` + ``post_comment`` path, with the board asserted
directly on ``FakeGitHub``'s own issue/comment state rather than a raw mock
(per ``docs/standards/testing/README.md``'s "don't replace FakeGitHub side
effects with raw mocks" rule).

There is no loop or phase wired to ``file_or_fold`` yet (Plan #1's scope is
the pure fold layer + CLI + agent-facing doc rule); this scenario simulates
a generic finder calling it across two ticks, matching the shape a real
finder (or the CLI-checked agent path) will drive once wired in.
"""

from __future__ import annotations

import pytest

from find_class_key import extract_class_key, extract_folded_sites, file_or_fold
from mockworld.fakes.fake_github import FakeGitHub

pytestmark = pytest.mark.scenario_loops


@pytest.mark.asyncio
async def test_tick_two_sibling_folds_into_tick_one_class_issue() -> None:
    gh = FakeGitHub()
    source = "branch-namespace-parser"
    needle = (
        "branch-to-issue parser recognizes agent/issue- but drops the "
        "agent/auto-agent-<N> namespace"
    )

    # Tick 1: the finder discovers the first site and sweeps it once.
    first_number = await file_or_fold(
        gh,
        source,
        needle,
        "StaleIssueLoop remote branch GC is blind to the agent/auto-agent-N namespace",
        "## Finding\n\nsrc/branch_gc_scan.py:39 misses agent/auto-agent-<N>",
        ["hydraflow-find"],
    )

    board_after_tick_one = await gh.list_issues_by_label("hydraflow-find")
    assert len(board_after_tick_one) == 1
    assert extract_class_key(board_after_tick_one[0]["body"])

    # Tick 2 (later cycle): a sibling site of the SAME class surfaces.
    second_number = await file_or_fold(
        gh,
        source,
        needle,
        "hydraflow-find: sibling branch parsers still drop the agent/auto-agent-<N> "
        "namespace (branch_gc_scan, pr_manager)",
        "## Finding\n\nsrc/pr_manager.py:3360 drops agent/auto-agent-<N> too",
        ["hydraflow-find"],
    )

    board_after_tick_two = await gh.list_issues_by_label("hydraflow-find")
    assert second_number == first_number
    assert len(board_after_tick_two) == 1
    assert len(gh._comments) == 1
    assert gh._comments[0][0] == first_number


@pytest.mark.asyncio
async def test_tick_three_rediscovering_tick_one_site_is_idempotent() -> None:
    """Cross-tick idempotency by site identifier, not title text (#11328).

    A site found again on a THIRD tick (with its title reworded from tick
    one) must produce no body change and no new comment — only the tick-two
    sibling site actually grows the roster.
    """
    gh = FakeGitHub()
    source = "branch-namespace-parser"
    needle = (
        "branch-to-issue parser recognizes agent/issue- but drops the "
        "agent/auto-agent-<N> namespace"
    )

    first_number = await file_or_fold(
        gh,
        source,
        needle,
        "StaleIssueLoop remote branch GC is blind to the agent/auto-agent-N namespace",
        "## Finding\n\nsrc/branch_gc_scan.py:39 misses agent/auto-agent-<N>",
        ["hydraflow-find"],
        site="src/branch_gc_scan.py:39",
    )

    second_number = await file_or_fold(
        gh,
        source,
        needle,
        "hydraflow-find: sibling branch parsers still drop the agent/auto-agent-<N> "
        "namespace (branch_gc_scan, pr_manager)",
        "## Finding\n\nsrc/pr_manager.py:3360 drops agent/auto-agent-<N> too",
        ["hydraflow-find"],
        site="src/pr_manager.py:3360",
    )
    assert second_number == first_number
    assert len(gh._comments) == 1

    board_after_tick_two = await gh.list_issues_by_label("hydraflow-find")
    body_after_tick_two = board_after_tick_two[0]["body"]
    assert extract_folded_sites(body_after_tick_two) == [
        "src/branch_gc_scan.py:39",
        "src/pr_manager.py:3360",
    ]

    # Tick 3: the SAME site as tick one resurfaces, reworded.
    third_number = await file_or_fold(
        gh,
        source,
        needle,
        "branch_gc_scan.py:39 still misses agent/auto-agent-<N> (re-scan)",
        "## Finding\n\nsrc/branch_gc_scan.py:39 misses agent/auto-agent-<N>",
        ["hydraflow-find"],
        site="src/branch_gc_scan.py:39",
    )
    assert third_number == first_number
    # No new comment, no roster change -- fully idempotent.
    assert len(gh._comments) == 1
    board_after_tick_three = await gh.list_issues_by_label("hydraflow-find")
    assert len(board_after_tick_three) == 1
    assert extract_folded_sites(board_after_tick_three[0]["body"]) == [
        "src/branch_gc_scan.py:39",
        "src/pr_manager.py:3360",
    ]


@pytest.mark.asyncio
async def test_closed_class_issue_is_never_reopened_or_commented_on() -> None:
    """A closed class issue is not a fold target (#11328 P3 acceptance bullet).

    Once the tick-one issue is closed, a later sibling site must file a
    FRESH issue rather than folding into (and implicitly reopening) the
    closed one -- ``list_issues_by_label`` only ever returns open issues,
    so ``match_class`` can't see it, but this pins the end-to-end behavior:
    no comment, no body edit, and the closed issue's state/body untouched.
    """
    gh = FakeGitHub()
    source = "branch-namespace-parser"
    needle = (
        "branch-to-issue parser recognizes agent/issue- but drops the "
        "agent/auto-agent-<N> namespace"
    )

    first_number = await file_or_fold(
        gh,
        source,
        needle,
        "StaleIssueLoop remote branch GC is blind to the agent/auto-agent-N namespace",
        "## Finding\n\nsrc/branch_gc_scan.py:39 misses agent/auto-agent-<N>",
        ["hydraflow-find"],
        site="src/branch_gc_scan.py:39",
    )
    body_before_close = gh._issues[first_number].body
    await gh.close_issue(first_number)

    second_number = await file_or_fold(
        gh,
        source,
        needle,
        "hydraflow-find: sibling branch parsers still drop the agent/auto-agent-<N> "
        "namespace (branch_gc_scan, pr_manager)",
        "## Finding\n\nsrc/pr_manager.py:3360 drops agent/auto-agent-<N> too",
        ["hydraflow-find"],
        site="src/pr_manager.py:3360",
    )

    assert second_number != first_number
    assert len(gh._comments) == 0
    assert gh._issues[first_number].state == "closed"
    assert gh._issues[first_number].body == body_before_close

    board = await gh.list_issues_by_label("hydraflow-find")
    assert len(board) == 1
    assert board[0]["number"] == second_number


@pytest.mark.asyncio
async def test_legacy_untagged_line_collision_binds_instead_of_dropping_site() -> None:
    """A genuinely new site colliding on title with a pre-#11328 legacy
    (untagged) roster line must still end up tracked (#11407), driven
    through a real ``FakeGitHub`` port end-to-end rather than a scripted
    double.
    """
    gh = FakeGitHub()
    source = "generic-null-check-finder"
    needle = "missing null check before dereference"
    colliding_title = "Missing null check"

    # Tick 1: a legacy-shaped issue -- filed and folded before per-site
    # identifiers existed, so its roster line carries no site tag.
    first_number = await file_or_fold(
        gh,
        source,
        needle,
        colliding_title,
        "## Finding\n\nsrc/original_site.py:5 missing null check",
        ["hydraflow-find"],
    )
    board_after_tick_one = await gh.list_issues_by_label("hydraflow-find")
    assert extract_folded_sites(board_after_tick_one[0]["body"]) == [colliding_title]

    # Tick 2: a site-aware caller reports a DIFFERENT site whose
    # finder-generated title happens to collide with the legacy line.
    second_number = await file_or_fold(
        gh,
        source,
        needle,
        colliding_title,
        "## Finding\n\nsrc/foo.py:12 missing null check",
        ["hydraflow-find"],
        site="src/foo.py:12",
    )

    assert second_number == first_number
    board_after_tick_two = await gh.list_issues_by_label("hydraflow-find")
    assert len(board_after_tick_two) == 1
    # The new site is now tracked in the roster -- not silently dropped.
    assert "src/foo.py:12" in extract_folded_sites(board_after_tick_two[0]["body"])


@pytest.mark.asyncio
async def test_distinct_needle_in_same_tick_still_files_its_own_issue() -> None:
    gh = FakeGitHub()
    await file_or_fold(
        gh,
        "branch-namespace-parser",
        "branch-to-issue parser drops agent/auto-agent-<N>",
        "branch parser namespace gap",
        "## Finding\n\ndetails",
        ["hydraflow-find"],
    )
    await file_or_fold(
        gh,
        "adr-pin-guard",
        "regression test hard-codes an ADR filename with no default lookup",
        "adr pin hardcodes filename",
        "## Finding\n\nunrelated details",
        ["hydraflow-find"],
    )

    board = await gh.list_issues_by_label("hydraflow-find")
    assert len(board) == 2
