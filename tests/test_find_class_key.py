"""Unit tests for the class-key fold layer (#11292).

Covers the pure matching engine (``normalize_needle``, ``compute_class_key``,
marker round-trip, ``title_token_overlap``, ``match_class``) and the
``file_or_fold`` orchestrator against a scripted fake ``PRPort``. Includes the
boundary/collision coverage that stalled the first implementation attempt on
this issue: degenerate needle inputs and a deliberately forced
truncated-digest collision, proving the needle-token backstop keeps two
unrelated needles from folding together even when their truncated class keys
collide.
"""

from __future__ import annotations

import pytest

from find_class_key import (
    CLASS_MARKER_TITLE_FLOOR,
    CLASS_OVERLAP_THRESHOLD,
    compute_class_key,
    extract_class_key,
    extract_folded_sites,
    file_or_fold,
    match_class,
    normalize_needle,
    render_marker,
    title_token_overlap,
)

_aio = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakePRPort:
    """Minimal scripted PRPort double recording file_or_fold's calls."""

    def __init__(self, issues: list[dict] | None = None) -> None:
        self._issues = {issue["number"]: dict(issue) for issue in (issues or [])}
        self._next_number = 9001
        self.update_calls: list[tuple[int, str]] = []
        self.comment_calls: list[tuple[int, str]] = []
        self.create_calls: list[tuple[str, str, list[str]]] = []

    async def list_issues_by_label(self, label: str) -> list[dict]:
        return [dict(issue) for issue in self._issues.values()]

    async def update_issue_body(self, issue_number: int, body: str) -> None:
        self.update_calls.append((issue_number, body))
        if issue_number in self._issues:
            self._issues[issue_number]["body"] = body

    async def post_comment(self, issue_number: int, body: str) -> None:
        self.comment_calls.append((issue_number, body))

    async def create_issue(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> int:
        self.create_calls.append((title, body, labels or []))
        number = self._next_number
        self._next_number += 1
        self._issues[number] = {"number": number, "title": title, "body": body}
        return number


class _FailingListPRPort(_FakePRPort):
    async def list_issues_by_label(self, label: str) -> list[dict]:
        raise RuntimeError("gh: rate limited")


# ---------------------------------------------------------------------------
# normalize_needle
# ---------------------------------------------------------------------------


class TestNormalizeNeedle:
    def test_strips_paths_line_numbers_and_issue_refs(self) -> None:
        a = normalize_needle(
            "src/branch_gc_scan.py:39 misses agent/auto-agent-<N>, see #11188"
        )
        b = normalize_needle(
            "src/pr_manager.py:3360 misses agent/auto-agent-<N>, see #11275"
        )
        assert a & b >= {"misses", "agent", "auto"}

    def test_empty_string_returns_empty_set(self) -> None:
        assert normalize_needle("") == frozenset()

    def test_whitespace_only_returns_empty_set(self) -> None:
        assert normalize_needle("   \n\t  ") == frozenset()

    def test_all_stopwords_and_numbers_returns_empty_set(self) -> None:
        assert normalize_needle("the pr #123 at 39 to a src") == frozenset()

    def test_single_and_double_char_tokens_are_dropped(self) -> None:
        assert normalize_needle("a N to gc") == frozenset()


# ---------------------------------------------------------------------------
# compute_class_key / marker round-trip
# ---------------------------------------------------------------------------


class TestComputeClassKey:
    def test_stable_regardless_of_site_wording(self) -> None:
        key_a = compute_class_key(
            "branch-parser", "branch-name parser missing agent/auto-agent-<N>"
        )
        key_b = compute_class_key(
            "branch-parser",
            "agent/auto-agent-<N> missing branch-name parser",
        )
        assert key_a == key_b

    def test_different_sources_never_collide_on_empty_needle(self) -> None:
        key_a = compute_class_key("finder-a", "")
        key_b = compute_class_key("finder-b", "")
        assert key_a != key_b

    def test_empty_needle_does_not_raise(self) -> None:
        key = compute_class_key("adr-pin", "")
        assert key.startswith("findclass:adr-pin:")

    def test_source_is_sanitized_into_the_key(self) -> None:
        key = compute_class_key("Weird Source!!", "some needle")
        assert key.startswith("findclass:weird-source:")

    def test_marker_round_trips_through_extract_class_key(self) -> None:
        key = compute_class_key("adr-pin", "non-self-retiring ADR pin")
        body = f"## Problem\n\ndetails\n\n{render_marker(key)}\n"
        assert extract_class_key(body) == key

    def test_extract_class_key_absent_returns_empty_string(self) -> None:
        assert extract_class_key("## Problem\n\nno marker here\n") == ""

    def test_extract_class_key_empty_body_returns_empty_string(self) -> None:
        assert extract_class_key("") == ""


# ---------------------------------------------------------------------------
# title_token_overlap / threshold boundary
# ---------------------------------------------------------------------------


class TestTitleTokenOverlap:
    def test_identical_titles_overlap_fully(self) -> None:
        assert title_token_overlap("branch parser gap", "branch parser gap") == 1.0

    def test_disjoint_titles_have_zero_overlap(self) -> None:
        assert title_token_overlap("branch parser gap", "adr pin renumbering") == 0.0

    def test_either_title_empty_after_normalization_returns_zero(self) -> None:
        assert title_token_overlap("the a to", "branch parser gap") == 0.0

    def test_overlap_at_threshold_boundary(self) -> None:
        # {alpha, bravo} vs {alpha, bravo, charlie, delta} -> 2/4 == 0.5
        overlap = title_token_overlap("alpha bravo", "alpha bravo charlie delta")
        assert overlap == CLASS_OVERLAP_THRESHOLD

    def test_overlap_just_below_threshold_boundary(self) -> None:
        # {alpha, bravo} vs {alpha, bravo, charlie, delta, echo} -> 2/5 == 0.4
        overlap = title_token_overlap("alpha bravo", "alpha bravo charlie delta echo")
        assert overlap < CLASS_OVERLAP_THRESHOLD


# ---------------------------------------------------------------------------
# extract_folded_sites
# ---------------------------------------------------------------------------


class TestExtractFoldedSites:
    def test_empty_body_returns_empty_list(self) -> None:
        assert extract_folded_sites("") == []

    def test_body_without_heading_returns_empty_list(self) -> None:
        assert extract_folded_sites("## Problem\n\nno sites section here\n") == []

    def test_legacy_lines_without_site_tag_use_title_text_as_identifier(self) -> None:
        body = (
            "## Problem\n\ndetails\n\n## Folded sites\n"
            "- first site title\n"
            "- second site title\n"
        )
        assert extract_folded_sites(body) == [
            "first site title",
            "second site title",
        ]

    def test_lines_with_explicit_site_tag_return_the_tagged_identifier(self) -> None:
        body = (
            "## Problem\n\ndetails\n\n## Folded sites\n"
            "- Human title A (site: `src/foo.py:39`)\n"
            "- Human title B (site: `src/bar.py:10`)\n"
        )
        assert extract_folded_sites(body) == [
            "src/foo.py:39",
            "src/bar.py:10",
        ]

    def test_stops_at_first_non_list_line_in_the_section(self) -> None:
        # A line under the heading that isn't a "- ..." bullet ends the
        # roster scan there -- fail-closed rather than skip over it and
        # risk picking up an unrelated bullet list further down the body.
        body = (
            "## Problem\n\ndetails\n\n## Folded sites\n"
            "- first site (site: `src/foo.py:39`)\n"
            "not a bullet line\n"
            "- never reached (site: `src/bar.py:10`)\n"
        )
        assert extract_folded_sites(body) == ["src/foo.py:39"]


# ---------------------------------------------------------------------------
# match_class
# ---------------------------------------------------------------------------


class TestMatchClass:
    def test_marker_equal_and_needle_shared_folds(self) -> None:
        key = compute_class_key("branch-parser", "branch namespace missing")
        issues = [
            {
                "number": 11188,
                "title": "branch namespace parser gap",
                "body": f"details\n\n{render_marker(key)}\n",
            }
        ]
        target = match_class(
            key,
            "branch namespace missing",
            "branch namespace parser gap at another site",
            issues,
        )
        assert target == 11188

    def test_marker_equal_needle_shared_but_title_unrelated_does_not_fold(
        self,
    ) -> None:
        # The needle-token backstop alone is not sufficient: 'branch' is a
        # coincidental shared word, but the candidate's title has nothing to
        # do with the matched issue's title -- the title-affinity floor
        # must refuse this fold even though the needle backstop would pass.
        key = compute_class_key("branch-parser", "branch namespace missing")
        issues = [
            {
                "number": 11188,
                "title": "branch namespace parser gap",
                "body": f"details\n\n{render_marker(key)}\n",
            }
        ]
        target = match_class(
            key, "branch namespace missing", "totally unrelated finding", issues
        )
        assert target == 0

    def test_marker_equal_title_affinity_at_floor_boundary_folds(self) -> None:
        key = compute_class_key("branch-parser", "branch namespace missing")
        issues = [
            {
                "number": 11188,
                "title": "branch namespace parser gap",
                "body": f"details\n\n{render_marker(key)}\n",
            }
        ]
        # {branch} shared of {branch, namespace, parser, gap, unrelated,
        # finding, extra, words, padded, out} -- engineered to sit at
        # CLASS_MARKER_TITLE_FLOOR exactly.
        overlap = title_token_overlap(
            "branch unrelated finding extra words padded out more",
            "branch namespace parser gap",
        )
        assert overlap >= CLASS_MARKER_TITLE_FLOOR
        target = match_class(
            key,
            "branch namespace missing",
            "branch unrelated finding extra words padded out more",
            issues,
        )
        assert target == 11188

    def test_marker_present_but_different_key_does_not_fold(self) -> None:
        other_key = compute_class_key("adr-pin", "non-self-retiring adr pin")
        candidate_key = compute_class_key("branch-parser", "branch namespace missing")
        issues = [
            {
                "number": 11192,
                "title": "adr pin hardcodes filename",
                "body": f"details\n\n{render_marker(other_key)}\n",
            }
        ]
        assert match_class(candidate_key, "branch namespace missing", "x", issues) == 0

    def test_truncated_digest_collision_does_not_cause_false_fold(self) -> None:
        # 'romeo' and 'whiskey' are engineered to collide at a 2-hex-char
        # truncation under the same source, while normalizing to disjoint
        # token sets -- exactly the truncation-collision shape the
        # first implementation attempt was missing coverage for.
        key_romeo = compute_class_key("branchparser", "romeo", digest_len=2)
        key_whiskey = compute_class_key("branchparser", "whiskey", digest_len=2)
        assert key_romeo == key_whiskey == "findclass:branchparser:ea"

        issues = [
            {
                "number": 5001,
                "title": "romeo finding",
                "body": f"about romeo\n\n{render_marker(key_romeo)}\n",
            }
        ]
        # Same key, but the candidate's needle ('whiskey') shares no token
        # with the matched issue's title/body -- must NOT fold.
        assert match_class(key_whiskey, "whiskey", "whiskey finding", issues) == 0
        # The genuine same-needle candidate still folds via the same marker.
        assert match_class(key_romeo, "romeo", "romeo finding v2", issues) == 5001

    def test_legacy_no_marker_needs_overlap_and_needle_in_body(self) -> None:
        key = compute_class_key("branch-parser", "branch namespace missing")
        issues = [
            {
                "number": 11275,
                "title": "sibling branch parsers still drop namespace",
                "body": "branch namespace missing everywhere, no marker here",
            }
        ]
        target = match_class(
            key,
            "branch namespace missing",
            "sibling branch parsers namespace gap",
            issues,
        )
        assert target == 11275

    def test_legacy_title_overlap_alone_without_needle_in_body_does_not_fold(
        self,
    ) -> None:
        key = compute_class_key("branch-parser", "branch namespace missing")
        issues = [
            {
                "number": 9999,
                "title": "sibling branch parsers namespace gap",
                "body": "completely unrelated content, no shared needle tokens",
            }
        ]
        target = match_class(
            key,
            "branch namespace missing",
            "sibling branch parsers namespace gap",
            issues,
        )
        assert target == 0

    def test_no_open_issues_returns_zero(self) -> None:
        key = compute_class_key("branch-parser", "branch namespace missing")
        assert match_class(key, "branch namespace missing", "title", []) == 0

    def test_cross_family_needles_do_not_fold(self) -> None:
        adr_key = compute_class_key("adr-pin", "non-self-retiring adr pin")
        fidelity_key = compute_class_key(
            "fakegithub-fidelity", "fakegithub run_gh unrecognised shape"
        )
        issues = [
            {
                "number": 11227,
                "title": "FakeGitHub tracks no branch refs",
                "body": f"fidelity gap\n\n{render_marker(fidelity_key)}\n",
            }
        ]
        target = match_class(adr_key, "non-self-retiring adr pin", "x", issues)
        assert target == 0


# ---------------------------------------------------------------------------
# file_or_fold
# ---------------------------------------------------------------------------


@_aio
class TestFileOrFold:
    async def test_first_call_creates_one_issue_with_marker(self) -> None:
        prs = _FakePRPort()
        number = await file_or_fold(
            prs,
            "branch-parser",
            "branch namespace missing",
            "branch_gc_scan misses agent/auto-agent-<N>",
            "## Problem\n\ndetails",
            ["hydraflow-find"],
        )
        assert number == 9001
        title, body, labels = prs.create_calls[0]
        assert title == "branch_gc_scan misses agent/auto-agent-<N>"
        assert "findclass:branch-parser:" in body
        assert labels == ["hydraflow-find"]

    async def test_second_call_same_class_folds_no_new_issue(self) -> None:
        prs = _FakePRPort()
        first = await file_or_fold(
            prs,
            "branch-parser",
            "branch namespace missing",
            "branch_gc_scan misses agent/auto-agent-<N>",
            "## Problem\n\ndetails",
            ["hydraflow-find"],
        )
        second = await file_or_fold(
            prs,
            "branch-parser",
            "branch namespace missing",
            "pr_manager misses agent/auto-agent-<N>",
            "## Problem\n\nsibling details",
            ["hydraflow-find"],
        )
        assert second == first
        assert len(prs.create_calls) == 1
        assert len(prs.comment_calls) == 1
        assert prs.comment_calls[0][0] == first

    async def test_refiling_already_listed_site_posts_no_second_comment(
        self,
    ) -> None:
        prs = _FakePRPort()
        title = "branch_gc_scan misses agent/auto-agent-<N>"
        first = await file_or_fold(
            prs,
            "branch-parser",
            "branch namespace missing",
            title,
            "## Problem\n\ndetails",
            ["hydraflow-find"],
        )
        # Same site rediscovered on a later tick.
        second = await file_or_fold(
            prs,
            "branch-parser",
            "branch namespace missing",
            title,
            "## Problem\n\ndetails",
            ["hydraflow-find"],
        )
        assert second == first
        assert len(prs.comment_calls) == 0
        assert len(prs.update_calls) == 0

    async def test_distinct_needle_files_its_own_issue(self) -> None:
        prs = _FakePRPort()
        first = await file_or_fold(
            prs,
            "branch-parser",
            "branch namespace missing",
            "branch_gc_scan misses agent/auto-agent-<N>",
            "## Problem\n\ndetails",
            ["hydraflow-find"],
        )
        second = await file_or_fold(
            prs,
            "adr-pin",
            "non-self-retiring adr pin",
            "test_issue_9565 hardcodes ADR-0007 filename",
            "## Problem\n\nunrelated",
            ["hydraflow-find"],
        )
        assert first != second
        assert len(prs.create_calls) == 2

    async def test_listing_failure_falls_through_to_file_new(self) -> None:
        prs = _FailingListPRPort()
        number = await file_or_fold(
            prs,
            "branch-parser",
            "branch namespace missing",
            "branch_gc_scan misses agent/auto-agent-<N>",
            "## Problem\n\ndetails",
            ["hydraflow-find"],
        )
        assert number == 9001
        assert len(prs.create_calls) == 1

    async def test_site_identifier_dedupes_across_reworded_titles(self) -> None:
        # A finder rediscovers the SAME site (file:line) on a later tick but
        # reworded the finding title -- idempotency must key off the site
        # identifier, not the exact title text (#11328).
        prs = _FakePRPort()
        first = await file_or_fold(
            prs,
            "branch-parser",
            "branch namespace missing",
            "branch_gc_scan misses agent/auto-agent-<N>",
            "## Problem\n\ndetails",
            ["hydraflow-find"],
            site="src/branch_gc_scan.py:39",
        )
        second = await file_or_fold(
            prs,
            "branch-parser",
            "branch namespace missing",
            "branch_gc_scan.py line 39 still misses agent/auto-agent-<N>",
            "## Problem\n\ndetails",
            ["hydraflow-find"],
            site="src/branch_gc_scan.py:39",
        )
        assert second == first
        assert len(prs.comment_calls) == 0
        assert len(prs.update_calls) == 0

    async def test_distinct_site_same_class_appends_new_roster_entry(self) -> None:
        prs = _FakePRPort()
        first = await file_or_fold(
            prs,
            "branch-parser",
            "branch namespace missing",
            "branch_gc_scan misses agent/auto-agent-<N>",
            "## Problem\n\ndetails",
            ["hydraflow-find"],
            site="src/branch_gc_scan.py:39",
        )
        second = await file_or_fold(
            prs,
            "branch-parser",
            "branch namespace missing",
            "pr_manager misses agent/auto-agent-<N>",
            "## Problem\n\nsibling details",
            ["hydraflow-find"],
            site="src/pr_manager.py:3360",
        )
        assert second == first
        assert len(prs.comment_calls) == 1
        folded_body = prs.update_calls[-1][1]
        assert extract_folded_sites(folded_body) == [
            "src/branch_gc_scan.py:39",
            "src/pr_manager.py:3360",
        ]

    async def test_site_omitted_falls_back_to_title_identity(self) -> None:
        # No explicit site passed -- behavior must match pre-#11328 title-only
        # idempotency exactly (backward compatibility for existing callers).
        prs = _FakePRPort()
        title = "branch_gc_scan misses agent/auto-agent-<N>"
        first = await file_or_fold(
            prs,
            "branch-parser",
            "branch namespace missing",
            title,
            "## Problem\n\ndetails",
            ["hydraflow-find"],
        )
        second = await file_or_fold(
            prs,
            "branch-parser",
            "branch namespace missing",
            title,
            "## Problem\n\ndetails",
            ["hydraflow-find"],
        )
        assert second == first
        assert len(prs.comment_calls) == 0
        assert len(prs.update_calls) == 0

    async def test_create_issue_zero_sentinel_propagates(self) -> None:
        class _ZeroCreatePRPort(_FakePRPort):
            async def create_issue(
                self, title: str, body: str, labels: list[str] | None = None
            ) -> int:
                self.create_calls.append((title, body, labels or []))
                return 0

        prs = _ZeroCreatePRPort()
        number = await file_or_fold(
            prs,
            "branch-parser",
            "branch namespace missing",
            "branch_gc_scan misses agent/auto-agent-<N>",
            "## Problem\n\ndetails",
            ["hydraflow-find"],
        )
        assert number == 0
