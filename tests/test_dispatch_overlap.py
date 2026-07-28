"""Unit tests for the dispatch-time scope-overlap guard (#10778)."""

from __future__ import annotations

from dispatch_overlap import (
    DispatchOverlapTracker,
    compute_scope,
    find_scope_overlap,
)
from models import Task


def _task(
    id: int, *, title: str = "", body: str = "", parent_epic: int | None = None
) -> Task:
    return Task(id=id, title=title, body=body, parent_epic=parent_epic)


class TestComputeScope:
    def test_extracts_referenced_issue_numbers_from_body(self) -> None:
        scope = compute_scope(_task(100, body="This also touches #10754 and #999."))
        assert scope.referenced_issues == frozenset({10754, 999})

    def test_extracts_reference_from_title(self) -> None:
        scope = compute_scope(_task(100, title="Fix regression seen in #4242"))
        assert 4242 in scope.referenced_issues

    def test_excludes_the_units_own_id(self) -> None:
        scope = compute_scope(_task(100, body="Fixes #100 by rewriting the loop."))
        assert 100 not in scope.referenced_issues

    def test_excludes_parent_epic_field(self) -> None:
        scope = compute_scope(_task(100, body="Child work; see #500.", parent_epic=500))
        assert 500 not in scope.referenced_issues

    def test_excludes_parent_epic_prose(self) -> None:
        scope = compute_scope(_task(100, body="Parent Epic: #777\n\nDo the thing."))
        assert 777 not in scope.referenced_issues

    def test_issue_scope_includes_own_id(self) -> None:
        scope = compute_scope(_task(100, body="relates to #42"))
        assert scope.issue_scope == frozenset({100, 42})

    def test_ignores_markdown_heading_hash(self) -> None:
        scope = compute_scope(_task(100, body="# Heading\n\nno refs here"))
        assert scope.referenced_issues == frozenset()

    def test_extracts_glob_file_token(self) -> None:
        scope = compute_scope(_task(100, body="edits the `wiki_rot_*.py` modules"))
        assert "wiki_rot_*.py" in scope.files

    def test_extracts_qualified_path_token(self) -> None:
        scope = compute_scope(_task(100, body="modify src/implement_phase.py here"))
        assert "src/implement_phase.py" in scope.files

    def test_excludes_generic_filenames(self) -> None:
        scope = compute_scope(_task(100, body="update README.md and __init__.py"))
        assert scope.files == frozenset()

    def test_bare_issue_has_empty_scope_signals(self) -> None:
        scope = compute_scope(_task(100, title="Refactor", body="no refs, no files"))
        assert scope.referenced_issues == frozenset() and scope.files == frozenset()


class TestFindScopeOverlap:
    def test_shared_referenced_issue_overlaps(self) -> None:
        a = compute_scope(_task(10772, body="touches #10754"))
        b = compute_scope(_task(10773, body="also touches #10754"))
        reason = find_scope_overlap(a, b)
        assert reason is not None and reason.kind == "issue"

    def test_shared_reference_detail_names_the_issue(self) -> None:
        a = compute_scope(_task(10772, body="touches #10754"))
        b = compute_scope(_task(10773, body="also touches #10754"))
        reason = find_scope_overlap(a, b)
        assert reason is not None and reason.detail == "#10754"

    def test_candidate_referencing_reserved_own_id_overlaps(self) -> None:
        candidate = compute_scope(_task(10773, body="depends on #10754"))
        reserved = compute_scope(_task(10754, body="the wiki entry"))
        assert find_scope_overlap(candidate, reserved) is not None

    def test_shared_file_token_overlaps(self) -> None:
        a = compute_scope(_task(1, body="edit `wiki_rot_*.py`"))
        b = compute_scope(_task(2, body="also edit `wiki_rot_*.py`"))
        reason = find_scope_overlap(a, b)
        assert reason is not None and reason.kind == "file"

    def test_distinct_ids_alone_do_not_overlap(self) -> None:
        a = compute_scope(_task(1, body="unrelated work"))
        b = compute_scope(_task(2, body="different unrelated work"))
        assert find_scope_overlap(a, b) is None

    def test_different_files_do_not_overlap(self) -> None:
        a = compute_scope(_task(1, body="edit src/a.py"))
        b = compute_scope(_task(2, body="edit src/b.py"))
        assert find_scope_overlap(a, b) is None


class TestDispatchOverlapTracker:
    def test_first_unit_is_reserved(self) -> None:
        tracker = DispatchOverlapTracker()
        assert tracker.reserve_or_hold(_task(1, body="touches #50")) is None

    def test_reserved_unit_is_tracked(self) -> None:
        tracker = DispatchOverlapTracker()
        tracker.reserve_or_hold(_task(1, body="touches #50"))
        assert tracker.reserved_ids == frozenset({1})

    def test_overlapping_second_unit_is_held(self) -> None:
        tracker = DispatchOverlapTracker()
        tracker.reserve_or_hold(_task(1, body="touches #50"))
        decision = tracker.reserve_or_hold(_task(2, body="also touches #50"))
        assert decision is not None

    def test_held_unit_reports_the_blocking_id(self) -> None:
        tracker = DispatchOverlapTracker()
        tracker.reserve_or_hold(_task(1, body="touches #50"))
        decision = tracker.reserve_or_hold(_task(2, body="also touches #50"))
        assert decision is not None and decision.blocking_id == 1

    def test_held_unit_is_not_reserved(self) -> None:
        tracker = DispatchOverlapTracker()
        tracker.reserve_or_hold(_task(1, body="touches #50"))
        tracker.reserve_or_hold(_task(2, body="also touches #50"))
        assert tracker.reserved_ids == frozenset({1})

    def test_non_overlapping_second_unit_is_reserved(self) -> None:
        tracker = DispatchOverlapTracker()
        tracker.reserve_or_hold(_task(1, body="touches #50"))
        assert tracker.reserve_or_hold(_task(2, body="touches #60")) is None

    def test_release_lets_previously_overlapping_unit_reserve(self) -> None:
        tracker = DispatchOverlapTracker()
        tracker.reserve_or_hold(_task(1, body="touches #50"))
        tracker.reserve_or_hold(_task(2, body="also touches #50"))
        tracker.release(1)
        assert tracker.reserve_or_hold(_task(2, body="also touches #50")) is None

    def test_release_is_idempotent(self) -> None:
        tracker = DispatchOverlapTracker()
        tracker.release(999)
        assert tracker.reserved_ids == frozenset()

    def test_two_bare_issues_never_hold_each_other(self) -> None:
        tracker = DispatchOverlapTracker()
        tracker.reserve_or_hold(_task(1, body="no refs or files"))
        assert tracker.reserve_or_hold(_task(2, body="also nothing")) is None
