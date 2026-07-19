"""Unit tests for the pure IssueGroomerLoop engine (#9957).

Covers ``normalize_title``, ``body_hash``, ``pair_key``, the
``find_dup_candidates`` prefilter, judgment-verdict parsing, judgment
prompts, guardrails, action tiering (``plan_actions``), and the digest
renderer. The module is pure (stdlib only, no I/O, no LLM spawns) so every
test operates on in-memory ``GroomIssue`` fixtures — no fakes, no ports.

Determinism is load-bearing here: ``find_dup_candidates`` must return the
same list, in the same order, given the same inputs (docs/superpowers/
specs/2026-07-19-issue-groomer-loop-design.md §2).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from issue_groomer import (
    GUARDRAIL_SKIP_LABELS,
    SETTLING_WINDOW_MINUTES,
    TITLE_WEIGHT,
    AutoClose,
    DigestProposal,
    DupVerdict,
    GroomIssue,
    PriorityQuestion,
    PriorityVerdict,
    RelabelAction,
    VerdictParseError,
    _jaccard,
    body_hash,
    build_dup_judgment_prompt,
    build_priority_prompt,
    find_dup_candidates,
    is_guarded,
    normalize_title,
    pair_key,
    parse_dup_verdict,
    parse_priority_verdict,
    plan_actions,
    render_digest,
)

_NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC)
_FRESH = _NOW.isoformat().replace("+00:00", "Z")
_STALE = (
    (_NOW - timedelta(minutes=SETTLING_WINDOW_MINUTES + 1))
    .isoformat()
    .replace("+00:00", "Z")
)


def _issue(
    number: int,
    title: str,
    body: str = "some body text here",
    labels: tuple[str, ...] = (),
    updated_at: str = "2026-07-01T00:00:00Z",
) -> GroomIssue:
    return GroomIssue(
        number=number,
        title=title,
        body=body,
        labels=labels,
        updated_at=updated_at,
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

    def test_strips_hash_ref_regardless_of_digit_count(self) -> None:
        """A real repo issue ref like #9957 is only 4 digits — must still
        strip identically to a title with no ref at all (sanctioned fix,
        Task 2 review: the old >=5-digit rule was inert for 4-digit refs)."""
        with_ref = normalize_title("Groomer engine tests failing (#9957)")
        without_ref = normalize_title("Groomer engine tests failing")

        assert with_ref == without_ref
        assert "9957" not in with_ref

    def test_strips_bare_four_digit_numbers_but_keeps_short_ones(self) -> None:
        result = normalize_title("Duplicate of issue 9957, see also 42")

        assert "9957" not in result
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

    def test_non_positive_budget_returns_empty(self) -> None:
        issues = _login_bug_family()

        assert (
            find_dup_candidates(issues, changed={1, 2, 3, 4}, judged=set(), budget=0)
            == []
        )
        assert (
            find_dup_candidates(issues, changed={1, 2, 3, 4}, judged=set(), budget=-3)
            == []
        )


class TestJaccardZeroUnion:
    """Direct coverage of ``_jaccard``'s zero-union branch (Task 2 review)."""

    def test_two_empty_sets_score_zero_without_dividing_by_zero(self) -> None:
        assert _jaccard(frozenset(), frozenset()) == 0.0

    def test_bodies_with_no_scoring_tokens_score_on_title_only(self) -> None:
        """Both bodies tokenize to an empty set (only <=3-char words), so
        the pair's body-overlap Jaccard hits the zero-union branch; the
        pair must still score (title-only) instead of crashing."""
        issues = [
            _issue(1, "Fix login bug", body="ok ok 42 1 2 3"),
            _issue(2, "Fix login bug", body="hi hi 7 8 9"),
        ]

        candidates = find_dup_candidates(
            issues, changed={1, 2}, judged=set(), budget=10
        )

        assert len(candidates) == 1
        assert candidates[0].score == pytest.approx(TITLE_WEIGHT)


class TestParseDupVerdict:
    def test_parses_fenced_json(self) -> None:
        text = (
            '```json\n{"verdict": "exact_dup", "canonical": 9665, '
            '"evidence": "same kill sites", "confidence": "high"}\n```'
        )

        verdict = parse_dup_verdict(text)

        assert verdict == DupVerdict(
            verdict="exact_dup",
            canonical=9665,
            evidence="same kill sites",
            confidence="high",
        )

    def test_parses_bare_json(self) -> None:
        text = (
            '{"verdict": "distinct", "canonical": 1, '
            '"evidence": "different root cause", "confidence": "low"}'
        )

        verdict = parse_dup_verdict(text)

        assert verdict.verdict == "distinct"
        assert verdict.confidence == "low"

    def test_garbage_raises_verdict_parse_error(self) -> None:
        with pytest.raises(VerdictParseError):
            parse_dup_verdict("not json at all, sorry")

    def test_missing_key_raises_verdict_parse_error(self) -> None:
        with pytest.raises(VerdictParseError):
            parse_dup_verdict('{"verdict": "exact_dup", "canonical": 1}')

    def test_unknown_verdict_value_raises_verdict_parse_error(self) -> None:
        with pytest.raises(VerdictParseError):
            parse_dup_verdict(
                '{"verdict": "maybe_dup", "canonical": 1, '
                '"evidence": "x", "confidence": "high"}'
            )

    def test_unknown_confidence_value_raises_verdict_parse_error(self) -> None:
        with pytest.raises(VerdictParseError):
            parse_dup_verdict(
                '{"verdict": "exact_dup", "canonical": 1, '
                '"evidence": "x", "confidence": "certain"}'
            )

    def test_non_int_canonical_raises_verdict_parse_error(self) -> None:
        with pytest.raises(VerdictParseError):
            parse_dup_verdict(
                '{"verdict": "exact_dup", "canonical": "9665", '
                '"evidence": "x", "confidence": "high"}'
            )


class TestParsePriorityVerdict:
    def test_parses_fenced_json(self) -> None:
        text = '```json\n{"priority": "P0", "reason": "blocks every RC"}\n```'

        verdict = parse_priority_verdict(text)

        assert verdict == PriorityVerdict(priority="P0", reason="blocks every RC")

    def test_parses_bare_json(self) -> None:
        verdict = parse_priority_verdict('{"priority": "none", "reason": "cosmetic"}')

        assert verdict.priority == "none"

    def test_garbage_raises_verdict_parse_error(self) -> None:
        with pytest.raises(VerdictParseError):
            parse_priority_verdict("<html>not json</html>")

    def test_missing_key_raises_verdict_parse_error(self) -> None:
        with pytest.raises(VerdictParseError):
            parse_priority_verdict('{"priority": "P1"}')

    def test_unknown_priority_value_raises_verdict_parse_error(self) -> None:
        with pytest.raises(VerdictParseError):
            parse_priority_verdict('{"priority": "P5", "reason": "x"}')


class TestPrompts:
    def test_dup_prompt_embeds_both_issues_and_rubric(self) -> None:
        a = _issue(1, "Fix login bug", body="the login page crashes on submit")
        b = _issue(2, "Fix login bug too", body="login page crash on submit")

        prompt = build_dup_judgment_prompt(a, b)

        assert "#1" in prompt
        assert "#2" in prompt
        assert "Fix login bug" in prompt
        assert "canonical" in prompt.lower()
        assert "exact_dup" in prompt
        assert len(prompt.splitlines()) < 120

    def test_priority_prompt_embeds_issue_and_rubric(self) -> None:
        issue = _issue(9974, "GateHealthLoop distributions", body="observability")

        prompt = build_priority_prompt(issue)

        assert "#9974" in prompt
        assert "GateHealthLoop distributions" in prompt
        assert "P0" in prompt and "P1" in prompt and "P2" in prompt
        assert len(prompt.splitlines()) < 120


class TestGuardrails:
    def test_known_phase_labels_are_guarded(self) -> None:
        for label in (
            "hydraflow-ready",
            "hydraflow-review",
            "hydraflow-hitl",
            "hydraflow-adr-drift",
            "hitl-escalation",
            "hydraflow-groom-digest",
        ):
            assert label in GUARDRAIL_SKIP_LABELS

    def test_is_guarded_true_when_issue_carries_skip_label(self) -> None:
        issue = _issue(1, "t", labels=("hydraflow-review",))

        assert is_guarded(issue) is True

    def test_is_guarded_false_for_plain_issue(self) -> None:
        issue = _issue(1, "t", labels=("P1",))

        assert is_guarded(issue) is False


class TestPlanActions:
    def test_exact_dup_high_unguarded_canonical_in_pair_autocloses(self) -> None:
        issues = {
            1: _issue(1, "a", updated_at=_STALE),
            2: _issue(2, "b", updated_at=_STALE),
        }
        verdict = DupVerdict(
            verdict="exact_dup", canonical=1, evidence="same bug", confidence="high"
        )

        actions = plan_actions({(1, 2): verdict}, {}, issues, now=_NOW)

        assert actions.auto_closes == (
            AutoClose(canonical=1, duplicate=2, evidence="same bug"),
        )
        assert actions.dup_proposals == ()

    def test_likely_dup_goes_to_digest_not_autoclose(self) -> None:
        issues = {1: _issue(1, "a"), 2: _issue(2, "b")}
        verdict = DupVerdict(
            verdict="likely_dup", canonical=1, evidence="overlap", confidence="high"
        )

        actions = plan_actions({(1, 2): verdict}, {}, issues, now=_NOW)

        assert actions.auto_closes == ()
        assert actions.dup_proposals == (DigestProposal(a=1, b=2, verdict=verdict),)

    def test_medium_confidence_exact_dup_goes_to_digest(self) -> None:
        issues = {1: _issue(1, "a"), 2: _issue(2, "b")}
        verdict = DupVerdict(
            verdict="exact_dup", canonical=1, evidence="overlap", confidence="medium"
        )

        actions = plan_actions({(1, 2): verdict}, {}, issues, now=_NOW)

        assert actions.auto_closes == ()
        assert len(actions.dup_proposals) == 1

    def test_guarded_side_blocks_autoclose_but_still_proposes(self) -> None:
        issues = {
            1: _issue(1, "a", labels=("hydraflow-review",)),
            2: _issue(2, "b"),
        }
        verdict = DupVerdict(
            verdict="exact_dup", canonical=1, evidence="same bug", confidence="high"
        )

        actions = plan_actions({(1, 2): verdict}, {}, issues, now=_NOW)

        assert actions.auto_closes == ()
        assert len(actions.dup_proposals) == 1

    def test_canonical_outside_pair_blocks_autoclose(self) -> None:
        issues = {1: _issue(1, "a"), 2: _issue(2, "b")}
        verdict = DupVerdict(
            verdict="exact_dup",
            canonical=999,
            evidence="rollup elsewhere",
            confidence="high",
        )

        actions = plan_actions({(1, 2): verdict}, {}, issues, now=_NOW)

        assert actions.auto_closes == ()
        assert len(actions.dup_proposals) == 1

    def test_relabel_when_differs_unguarded_and_settled(self) -> None:
        issues = {1: _issue(1, "a", labels=("P2",), updated_at=_STALE)}
        priority = PriorityVerdict(priority="P0", reason="blocks throughput")

        actions = plan_actions({}, {1: priority}, issues, now=_NOW)

        assert actions.relabels == (
            RelabelAction(
                number=1, previous="P2", priority="P0", reason="blocks throughput"
            ),
        )
        assert actions.priority_questions == ()

    def test_fresh_issue_not_relabeled(self) -> None:
        """Settling window: an issue touched moments ago is left for a
        later tick even though its priority verdict differs."""
        issues = {1: _issue(1, "a", labels=("P2",), updated_at=_FRESH)}
        priority = PriorityVerdict(priority="P0", reason="blocks throughput")

        actions = plan_actions({}, {1: priority}, issues, now=_NOW)

        assert actions.relabels == ()
        assert actions.priority_questions == ()

    def test_guarded_issue_not_relabeled(self) -> None:
        issues = {
            1: _issue(1, "a", labels=("P2", "hydraflow-review"), updated_at=_STALE)
        }
        priority = PriorityVerdict(priority="P0", reason="blocks throughput")

        actions = plan_actions({}, {1: priority}, issues, now=_NOW)

        assert actions.relabels == ()
        assert actions.priority_questions == ()

    def test_same_priority_as_current_is_a_no_op(self) -> None:
        issues = {1: _issue(1, "a", labels=("P1",), updated_at=_STALE)}
        priority = PriorityVerdict(priority="P1", reason="still P1")

        actions = plan_actions({}, {1: priority}, issues, now=_NOW)

        assert actions.relabels == ()
        assert actions.priority_questions == ()

    def test_relabel_to_none_routes_to_digest_question_not_relabel(self) -> None:
        issues = {1: _issue(1, "a", labels=("P1",), updated_at=_STALE)}
        priority = PriorityVerdict(priority="none", reason="no longer relevant")

        actions = plan_actions({}, {1: priority}, issues, now=_NOW)

        assert actions.relabels == ()
        assert actions.priority_questions == (
            PriorityQuestion(
                number=1, current="P1", proposed="none", reason="no longer relevant"
            ),
        )


class TestRenderDigest:
    def test_empty_actions_render_all_four_headers_with_placeholder(self) -> None:
        actions = plan_actions({}, {}, {}, now=_NOW)

        digest = render_digest(actions, stats={})

        assert "## Proposed closes" in digest
        assert "## Priority changes applied" in digest
        assert "## Operator questions" in digest
        assert "## Stats" in digest
        assert digest.count("_none this tick_") == 4

    def test_renders_one_row_per_populated_section(self) -> None:
        issues = {
            1: _issue(1, "a", updated_at=_STALE),
            2: _issue(2, "b", updated_at=_STALE),
            3: _issue(3, "c", labels=("P2",), updated_at=_STALE),
            4: _issue(4, "d"),
            5: _issue(5, "e"),
        }
        dup_verdict = DupVerdict(
            verdict="exact_dup", canonical=1, evidence="same bug", confidence="high"
        )
        distinct_verdict = DupVerdict(
            verdict="distinct", canonical=4, evidence="different", confidence="high"
        )
        priorities = {
            3: PriorityVerdict(priority="P0", reason="throughput blocker"),
        }

        actions = plan_actions(
            {(1, 2): dup_verdict, (4, 5): distinct_verdict},
            priorities,
            issues,
            now=_NOW,
        )
        digest = render_digest(actions, stats={"backlog": 5, "pairs_judged": 2})

        assert "#2: duplicate of #1" in digest
        assert "same bug" in digest
        assert "#3: P2 -> P0" in digest
        assert "#4 vs #5: distinct" in digest
        assert "- backlog: 5" in digest
        assert "- pairs_judged: 2" in digest
