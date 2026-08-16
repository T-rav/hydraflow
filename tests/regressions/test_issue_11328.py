"""Regression pin for #11328: cross-tick folding of new sites into open
class-level issues.

Child 3 of the #11292 board-growth decomposition (Epic #11325). The core
matching engine (``compute_class_key`` / ``match_class`` / ``file_or_fold``)
already shipped in #11324, which closed the parent #11292 directly and, with
it, sibling Child 2 (#11327). What #11324 did NOT cover is this issue's own
acceptance bullets:

* idempotency keyed on a stable *site identifier* (file:line or
  equivalent), not on the exact issue-title text -- a finder that reworks
  its title between ticks must still recognize a rediscovered site as a
  no-op;
* a public accessor (``extract_folded_sites``) to read the site roster
  back out of an issue body, so callers (and the CLI shell) can check
  "is this specific site already listed" without re-deriving the parsing
  logic;
* the title/needle-token overlap guard against a truncated-digest key
  collision, which #11292's issue #11324 already built via a needle-token
  backstop (pinned again here from the acceptance-criteria angle).

This module pins the exact T1/T2/T3 cross-tick scenario from the issue's
acceptance section directly against ``find_class_key.file_or_fold``.
"""

from __future__ import annotations

import pytest

from find_class_key import (
    compute_class_key,
    extract_folded_sites,
    file_or_fold,
    match_class,
    render_marker,
)


class _RecordingPRPort:
    """Scripted PRPort double recording file_or_fold's calls."""

    def __init__(self) -> None:
        self._issues: dict[int, dict] = {}
        self._next_number = 30000
        self.comment_calls: list[tuple[int, str]] = []
        self.update_calls: list[tuple[int, str]] = []

    async def list_issues_by_label(self, label: str) -> list[dict]:
        return [dict(issue) for issue in self._issues.values()]

    async def update_issue_body(self, issue_number: int, body: str) -> None:
        self.update_calls.append((issue_number, body))
        self._issues[issue_number]["body"] = body

    async def post_comment(self, issue_number: int, body: str) -> None:
        self.comment_calls.append((issue_number, body))

    async def create_issue(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> int:
        number = self._next_number
        self._next_number += 1
        self._issues[number] = {"number": number, "title": title, "body": body}
        return number


_SOURCE = "branch-namespace-parser"
_NEEDLE = (
    "branch-to-issue parser recognizes agent/issue- but drops the "
    "agent/auto-agent-<N> namespace"
)


@pytest.mark.asyncio
async def test_tick_two_site_folds_into_tick_one_issue_no_new_issue_filed() -> None:
    """Acceptance bullet 1: T1 files, T2's sibling site folds into it."""
    prs = _RecordingPRPort()

    t1_number = await file_or_fold(
        prs,
        _SOURCE,
        _NEEDLE,
        "branch_gc_scan misses agent/auto-agent-<N>",
        "## Finding\n\nsrc/branch_gc_scan.py:39 misses agent/auto-agent-<N>",
        ["hydraflow-find"],
        site="src/branch_gc_scan.py:39",
    )
    t2_number = await file_or_fold(
        prs,
        _SOURCE,
        _NEEDLE,
        "pr_manager also misses agent/auto-agent-<N>",
        "## Finding\n\nsrc/pr_manager.py:3360 misses agent/auto-agent-<N>",
        ["hydraflow-find"],
        site="src/pr_manager.py:3360",
    )

    assert t2_number == t1_number
    assert len(prs._issues) == 1
    body = prs._issues[t1_number]["body"]
    assert extract_folded_sites(body) == [
        "src/branch_gc_scan.py:39",
        "src/pr_manager.py:3360",
    ]


@pytest.mark.asyncio
async def test_tick_three_rediscovering_tick_one_site_is_idempotent() -> None:
    """Acceptance bullet 2: T3 rediscovering X (already listed) is a no-op."""
    prs = _RecordingPRPort()

    t1_number = await file_or_fold(
        prs,
        _SOURCE,
        _NEEDLE,
        "branch_gc_scan misses agent/auto-agent-<N>",
        "## Finding\n\nsrc/branch_gc_scan.py:39 misses agent/auto-agent-<N>",
        ["hydraflow-find"],
        site="src/branch_gc_scan.py:39",
    )
    await file_or_fold(
        prs,
        _SOURCE,
        _NEEDLE,
        "pr_manager also misses agent/auto-agent-<N>",
        "## Finding\n\nsrc/pr_manager.py:3360 misses agent/auto-agent-<N>",
        ["hydraflow-find"],
        site="src/pr_manager.py:3360",
    )
    body_before = prs._issues[t1_number]["body"]

    # T3: same site as T1 resurfaces with a reworded title -- must be a no-op.
    t3_number = await file_or_fold(
        prs,
        _SOURCE,
        _NEEDLE,
        "branch_gc_scan.py:39 STILL misses agent/auto-agent-<N> (re-swept)",
        "## Finding\n\nsrc/branch_gc_scan.py:39 misses agent/auto-agent-<N>",
        ["hydraflow-find"],
        site="src/branch_gc_scan.py:39",
    )

    assert t3_number == t1_number
    assert len(prs._issues) == 1
    assert prs._issues[t1_number]["body"] == body_before
    # Exactly one fold comment (from T2); T3 posts none.
    assert len(prs.comment_calls) == 1


@pytest.mark.asyncio
async def test_site_aware_rediscovery_of_pre_11328_title_only_roster_line_is_idempotent() -> (
    None
):
    """Legacy issues (filed before #11328) roster sites by title text alone.

    A later, site-aware rediscovery of that SAME finding (identical title,
    now with an explicit ``--site``) must recognize the title-only line as
    already folded instead of appending a second, site-tagged line for the
    same site -- the duplicate-roster-line bug caught in review: the
    site-aware lookup only ever checked the site identifier, which a
    pre-#11328 line never carries.
    """
    prs = _RecordingPRPort()
    title = "branch_gc_scan misses agent/auto-agent-<N>"
    class_key = compute_class_key(_SOURCE, _NEEDLE)
    legacy_body = (
        "## Finding\n\nsrc/branch_gc_scan.py:39 misses agent/auto-agent-<N>\n\n"
        "## Folded sites\n"
        f"- {title}\n\n"
        f"{render_marker(class_key)}\n"
    )
    prs._issues[30000] = {
        "number": 30000,
        "title": title,
        "body": legacy_body,
    }
    prs._next_number = 30001

    result_number = await file_or_fold(
        prs,
        _SOURCE,
        _NEEDLE,
        title,
        "## Finding\n\nsrc/branch_gc_scan.py:39 misses agent/auto-agent-<N>",
        ["hydraflow-find"],
        site="src/branch_gc_scan.py:39",
    )

    assert result_number == 30000
    assert len(prs._issues) == 1
    assert prs._issues[30000]["body"] == legacy_body
    assert extract_folded_sites(legacy_body) == [title]
    assert len(prs.comment_calls) == 0
    assert len(prs.update_calls) == 0


@pytest.mark.asyncio
async def test_no_matching_open_class_issue_files_new_issue() -> None:
    """Acceptance bullet 3: no open class issue -> a new one is filed."""
    prs = _RecordingPRPort()

    number = await file_or_fold(
        prs,
        _SOURCE,
        _NEEDLE,
        "branch_gc_scan misses agent/auto-agent-<N>",
        "## Finding\n\ndetails",
        ["hydraflow-find"],
        site="src/branch_gc_scan.py:39",
    )

    assert len(prs._issues) == 1
    assert prs._issues[number]["title"] == "branch_gc_scan misses agent/auto-agent-<N>"


@pytest.mark.asyncio
async def test_title_token_overlap_guard_prevents_hash_collision_fold() -> None:
    """Acceptance bullet 4: a truncated class-key hash collision must not fold.

    Two needles engineered to collide at a short digest truncation, but
    which share no title/needle tokens, must file as two separate issues --
    the secondary title/needle-overlap guard against a false key match.
    """
    key_a = compute_class_key(_SOURCE, "romeo", digest_len=2)
    key_b = compute_class_key(_SOURCE, "whiskey", digest_len=2)
    assert key_a == key_b, "test setup requires an engineered digest collision"

    issues = [
        {
            "number": 40001,
            "title": "romeo finding",
            "body": f"about romeo\n\n{render_marker(key_a)}\n",
        }
    ]
    # Same class key, but 'whiskey' shares no needle token with the matched
    # issue's title/body -- the overlap guard must refuse the fold.
    assert match_class(key_b, "whiskey", "whiskey finding", issues) == 0
