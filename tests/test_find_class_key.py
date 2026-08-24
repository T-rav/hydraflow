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

    @pytest.mark.parametrize(
        "needle",
        [
            "",
            "   \n\t  ",
            "the pr #123 at 39 to a src",
            "a N to gc",
        ],
        ids=[
            "empty_string_returns_empty_set",
            "whitespace_only_returns_empty_set",
            "all_stopwords_and_numbers_returns_empty_set",
            "single_and_double_char_tokens_are_dropped",
        ],
    )
    def test_needle_with_no_significant_tokens_returns_empty_set(
        self, needle: str
    ) -> None:
        assert normalize_needle(needle) == frozenset()


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

    # {branch} shared of {branch, namespace, parser, gap} union 16 unique
    # filler tokens -- 1 / (4 + 17 - 1) == 0.05, CLASS_MARKER_TITLE_FLOOR
    # exactly. One fewer filler word (17 unique, union 21) drops just below
    # it. Both titles are asserted against a live `title_token_overlap` call
    # rather than a hard-coded literal, so a floor-arithmetic typo here
    # can't silently drift from what CLASS_MARKER_TITLE_FLOOR actually is.
    _TITLE_AT_FLOOR = (
        "branch alpha bravo charlie delta echo foxtrot golf hotel india "
        "juliett kilo lima mike november oscar papa"
    )
    _TITLE_JUST_BELOW_FLOOR = _TITLE_AT_FLOOR + " quebec"

    def test_marker_equal_title_affinity_at_floor_boundary_folds(self) -> None:
        key = compute_class_key("branch-parser", "branch namespace missing")
        issues = [
            {
                "number": 11188,
                "title": "branch namespace parser gap",
                "body": f"details\n\n{render_marker(key)}\n",
            }
        ]
        overlap = title_token_overlap(
            self._TITLE_AT_FLOOR, "branch namespace parser gap"
        )
        assert overlap == pytest.approx(CLASS_MARKER_TITLE_FLOOR)
        target = match_class(
            key, "branch namespace missing", self._TITLE_AT_FLOOR, issues
        )
        assert target == 11188

    def test_marker_equal_title_affinity_just_below_floor_does_not_fold(
        self,
    ) -> None:
        key = compute_class_key("branch-parser", "branch namespace missing")
        issues = [
            {
                "number": 11188,
                "title": "branch namespace parser gap",
                "body": f"details\n\n{render_marker(key)}\n",
            }
        ]
        overlap = title_token_overlap(
            self._TITLE_JUST_BELOW_FLOOR, "branch namespace parser gap"
        )
        assert overlap < CLASS_MARKER_TITLE_FLOOR
        target = match_class(
            key, "branch namespace missing", self._TITLE_JUST_BELOW_FLOOR, issues
        )
        assert target == 0

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

    async def test_title_with_embedded_newline_does_not_truncate_roster(
        self,
    ) -> None:
        # A title containing a raw newline must not corrupt the rendered
        # roster line into two physical lines -- extract_folded_sites stops
        # at the first non-"- " line, so an unescaped newline would drop
        # every site folded in after it (#11328 round-trip regression).
        prs = _FakePRPort()
        first = await file_or_fold(
            prs,
            "branch-parser",
            "branch namespace missing",
            "branch_gc_scan misses\nagent/auto-agent-<N>",
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
        folded_body = prs.update_calls[-1][1]
        assert extract_folded_sites(folded_body) == [
            "src/branch_gc_scan.py:39",
            "src/pr_manager.py:3360",
        ]

        # The newline-titled site rediscovered on a later tick is still a
        # true no-op -- proves the roster and the dedup check agree on the
        # same (sanitized) identifier.
        third = await file_or_fold(
            prs,
            "branch-parser",
            "branch namespace missing",
            "branch_gc_scan misses\nagent/auto-agent-<N>",
            "## Problem\n\ndetails",
            ["hydraflow-find"],
            site="src/branch_gc_scan.py:39",
        )
        assert third == first
        assert len(prs.comment_calls) == 1
        assert len(prs.update_calls) == 1

    async def test_site_identifier_with_backtick_round_trips(self) -> None:
        # A site identifier containing a backtick must not break the
        # ``(site: `X`)`` delimiter -- a corrupted round trip would make the
        # site permanently unrecognizable, re-folding (and re-commenting)
        # every tick (#11328 round-trip regression).
        prs = _FakePRPort()
        site = "src/foo.py:39 (in `bar()`)"
        first = await file_or_fold(
            prs,
            "branch-parser",
            "branch namespace missing",
            "branch_gc_scan misses agent/auto-agent-<N>",
            "## Problem\n\ndetails",
            ["hydraflow-find"],
            site=site,
        )
        second = await file_or_fold(
            prs,
            "branch-parser",
            "branch namespace missing",
            "branch_gc_scan.py line 39 still misses agent/auto-agent-<N>",
            "## Problem\n\ndetails",
            ["hydraflow-find"],
            site=site,
        )
        assert second == first
        assert len(prs.comment_calls) == 0
        assert len(prs.update_calls) == 0

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

    async def test_bind_fallback_appends_fresh_line_when_no_bare_line_matches(
        self,
    ) -> None:
        # `title in existing_sites` can also be satisfied by an unrelated
        # TAGGED line whose SITE value happens to equal the current call's
        # title text -- not a bare/untagged line at all. The bind attempt
        # must not silently drop the new site in that case: it falls
        # through to appending a fresh roster entry instead (#11407
        # defensive fallback in ``_bind_bare_line``).
        prs = _FakePRPort()
        class_key = compute_class_key("branch-parser", "branch namespace missing")
        body = (
            "## Problem\n\ndetails\n\n## Folded sites\n"
            "- Some Other Title (site: `Missing null check`)\n\n"
            f"{render_marker(class_key)}\n"
        )
        prs._issues[7001] = {
            "number": 7001,
            "title": "Missing null check duplicate finding",
            "body": body,
        }
        prs._next_number = 7002

        result = await file_or_fold(
            prs,
            "branch-parser",
            "branch namespace missing",
            "Missing null check",
            "## Problem\n\nunrelated",
            ["hydraflow-find"],
            site="src/foo.py:12",
        )

        assert result == 7001
        updated_body = prs._issues[7001]["body"]
        assert extract_folded_sites(updated_body) == [
            "Missing null check",
            "src/foo.py:12",
        ]
        # The fallback appends a genuinely new roster entry -- roster grew,
        # so the fold comment fires and the body change is persisted.
        assert len(prs.comment_calls) == 1
        assert len(prs.update_calls) == 1

    async def test_bind_does_not_rewrite_a_bare_line_outside_the_roster_block(
        self,
    ) -> None:
        # `_bind_bare_line`'s scan must stop at the roster's contiguous
        # block boundary, exactly like `_append_site`'s own insert loop --
        # a bare `- {title}` bullet appearing in a LATER section (after the
        # roster ends) must never be mistaken for the legacy roster line
        # and rewritten, even when the ambiguous-collision fallback path
        # (a tagged roster line whose SITE value equals *title*) is what
        # routed the call here. Silently rewriting unrelated body content
        # would also mean the new site is never rostered at all.
        prs = _FakePRPort()
        class_key = compute_class_key("branch-parser", "branch namespace missing")
        body = (
            "## Problem\n\ndetails\n\n## Folded sites\n"
            "- Some Other Title (site: `Missing null check`)\n\n"
            "## Notes\n"
            "- Missing null check\n"
            "- something unrelated\n\n"
            f"{render_marker(class_key)}\n"
        )
        prs._issues[7101] = {
            "number": 7101,
            "title": "Missing null check duplicate finding",
            "body": body,
        }
        prs._next_number = 7102

        result = await file_or_fold(
            prs,
            "branch-parser",
            "branch namespace missing",
            "Missing null check",
            "## Problem\n\nunrelated",
            ["hydraflow-find"],
            site="src/foo.py:12",
        )

        assert result == 7101
        updated_body = prs._issues[7101]["body"]
        # The unrelated "## Notes" bullet must survive untouched.
        assert "- Missing null check\n" in updated_body
        # The new site must land in the roster via a fresh appended line,
        # not be lost by binding to the unrelated later bullet.
        assert extract_folded_sites(updated_body) == [
            "Missing null check",
            "src/foo.py:12",
        ]
        assert len(prs.comment_calls) == 1
        assert len(prs.update_calls) == 1

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
