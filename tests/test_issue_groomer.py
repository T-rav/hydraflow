"""Unit tests for the pure IssueGroomerLoop engine (#9957).

Covers ``normalize_title``, ``body_hash``, ``pair_key``, and the
``find_dup_candidates`` prefilter. The module is pure (stdlib only, no
I/O, no LLM spawns) so every test operates on in-memory ``GroomIssue``
fixtures — no fakes, no ports.

Determinism is load-bearing here: ``find_dup_candidates`` must return the
same list, in the same order, given the same inputs (docs/superpowers/
specs/2026-07-19-issue-groomer-loop-design.md §2).
"""

from __future__ import annotations

from issue_groomer import (
    GroomIssue,
    body_hash,
    find_dup_candidates,
    normalize_title,
    pair_key,
)


def _issue(
    number: int,
    title: str,
    body: str = "some body text here",
) -> GroomIssue:
    return GroomIssue(
        number=number,
        title=title,
        body=body,
        labels=(),
        updated_at="2026-07-01T00:00:00Z",
    )


def _login_bug_family() -> list[GroomIssue]:
    """Four issues: 1/2/4 are near-dups of each other, 3 is unrelated."""
    return [
        _issue(1, "Fix login bug", body="the login page crashes on submit"),
        _issue(2, "Fix login bug", body="the login page crashes on submit too"),
        _issue(3, "Add dark mode toggle", body="totally unrelated feature request"),
        _issue(4, "Fix login bug", body="the login page crashes on submission"),
    ]


class TestNormalizeTitle:
    def test_lowercases_and_collapses_whitespace(self) -> None:
        result = normalize_title("  Fix   Login   Bug  ")

        assert result == "fix login bug"

    def test_strips_punctuation(self) -> None:
        result = normalize_title("Fix: login-bug!! (again)")

        assert result == "fix login bug again"

    def test_strips_issue_ref_numbers_but_keeps_short_numbers(self) -> None:
        result = normalize_title("Fix bug from #12345, duplicate of issue 42")

        assert "12345" not in result
        assert "42" in result


class TestBodyHash:
    def test_is_twelve_hex_chars(self) -> None:
        digest = body_hash("some body text")

        assert len(digest) == 12
        assert all(c in "0123456789abcdef" for c in digest)

    def test_different_bodies_hash_differently(self) -> None:
        assert body_hash("body one") != body_hash("body two")

    def test_same_body_hashes_identically(self) -> None:
        assert body_hash("same body") == body_hash("same body")


class TestPairKey:
    def test_orders_by_min_max_issue_number(self) -> None:
        a = _issue(20, "a", body="body a")
        b = _issue(5, "b", body="body b")

        key = pair_key(a, b)

        assert key.startswith("5:20:")
        assert pair_key(a, b) == pair_key(b, a)

    def test_body_edit_on_either_side_changes_key(self) -> None:
        a = _issue(1, "a", body="original body")
        b = _issue(2, "b", body="other body")
        key_before = pair_key(a, b)

        key_after_a_edit = pair_key(_issue(1, "a", body="edited body"), b)
        key_after_b_edit = pair_key(a, _issue(2, "b", body="also edited"))

        assert key_after_a_edit != key_before
        assert key_after_b_edit != key_before
        assert key_after_a_edit != key_after_b_edit


class TestFindDupCandidates:
    def test_identical_titles_rank_first(self) -> None:
        issues = _login_bug_family()

        candidates = find_dup_candidates(
            issues, changed={1, 2, 3, 4}, judged=set(), budget=10
        )

        assert candidates[0].a == 1
        assert candidates[0].b == 2
        assert candidates[0].score > 0.9

    def test_excludes_pairs_with_neither_side_changed(self) -> None:
        issues = _login_bug_family()[:2]

        candidates = find_dup_candidates(issues, changed=set(), judged=set(), budget=10)

        assert candidates == []

    def test_includes_pair_when_only_one_side_changed(self) -> None:
        issues = _login_bug_family()[:2]

        candidates = find_dup_candidates(issues, changed={2}, judged=set(), budget=10)

        assert len(candidates) == 1
        assert candidates[0].a == 1
        assert candidates[0].b == 2

    def test_skips_pairs_already_in_judged_cache(self) -> None:
        issues = _login_bug_family()
        already_judged = pair_key(issues[0], issues[1])

        candidates = find_dup_candidates(
            issues, changed={1, 2, 3, 4}, judged={already_judged}, budget=10
        )

        assert (1, 2) not in [(c.a, c.b) for c in candidates]

    def test_drops_pairs_below_score_floor(self) -> None:
        issues = [
            _issue(1, "Fix login bug", body="the login page crashes on submit"),
            _issue(2, "Add dark mode toggle", body="totally unrelated feature request"),
        ]

        candidates = find_dup_candidates(
            issues, changed={1, 2}, judged=set(), budget=10
        )

        assert candidates == []

    def test_slices_to_budget(self) -> None:
        issues = _login_bug_family()

        full = find_dup_candidates(
            issues, changed={1, 2, 3, 4}, judged=set(), budget=10
        )
        sliced = find_dup_candidates(
            issues, changed={1, 2, 3, 4}, judged=set(), budget=1
        )

        assert len(full) > 1
        assert sliced == full[:1]

    def test_deterministic_across_repeated_calls(self) -> None:
        issues = _login_bug_family()

        first = find_dup_candidates(
            issues, changed={1, 2, 3, 4}, judged=set(), budget=10
        )
        second = find_dup_candidates(
            issues, changed={1, 2, 3, 4}, judged=set(), budget=10
        )

        assert first == second
