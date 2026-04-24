"""Unit tests for src/corpus_learning_loop.py (§4.1 Phase 2 skeleton + Tasks 12–14).

Covers:

- construction (worker_name wired, deps stored)
- ``_get_default_interval`` reads ``config.corpus_learning_interval``
- ``_do_work`` short-circuits with ``{"status": "disabled"}`` when the
  ``enabled_cb`` kill-switch returns ``False``
- Task 11 escape-signal reader: ``_list_escape_signals`` parses
  ``PRManager.list_issues_by_label`` output into :class:`EscapeSignal`
  dataclasses, filters to the configured lookback window, short-circuits
  cleanly on empty input, and is invoked by ``_do_work`` when enabled.
- Task 12 in-process case synthesis: :meth:`CorpusLearningLoop._synthesize_case`
  turns a parseable :class:`EscapeSignal` into a :class:`SynthesizedCase`
  and returns ``None`` on malformed/minimal signals (loop skips, not
  crashes).
- Task 13 three-gate self-validation: :meth:`CorpusLearningLoop._validate_case`
  reports :class:`ValidationResult` with the correct failing gate for
  empty diffs (gate a), non-tripping catchers (gate b), and
  marker collisions where an unintended catcher also fires (gate c).
- Task 14 wiring into ``_do_work``: enriched status dict reports
  ``escape_issues_seen``, ``cases_synthesized`` (envelope parsed), and
  ``cases_validated`` (all three gates green) without opening PRs.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from corpus_learning_loop import (
    DEFAULT_ESCAPE_LABEL,
    DEFAULT_LOOKBACK_DAYS,
    CorpusLearningLoop,
    EscapeSignal,
    SynthesizedCase,
    ValidationResult,
)
from events import EventBus


def _deps(stop: asyncio.Event, *, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


def _loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    prs: object | None = None,
    **config_overrides: object,
) -> CorpusLearningLoop:
    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        **config_overrides,
    )
    pr_manager = prs if prs is not None else AsyncMock()
    dedup = MagicMock()
    return CorpusLearningLoop(
        config=cfg,
        prs=pr_manager,
        dedup=dedup,
        deps=_deps(asyncio.Event(), enabled=enabled),
    )


def test_loop_constructs_with_expected_worker_name(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    assert loop._worker_name == "corpus_learning"


def test_default_interval_reads_from_config(tmp_path: Path) -> None:
    # Default from the ``corpus_learning_interval`` Field (weekly cadence).
    loop = _loop(tmp_path)
    assert loop._get_default_interval() == 604800


def test_default_interval_reflects_config_override(tmp_path: Path) -> None:
    loop = _loop(tmp_path, corpus_learning_interval=7200)
    assert loop._get_default_interval() == 7200


def test_do_work_short_circuits_when_kill_switch_disabled(tmp_path: Path) -> None:
    loop = _loop(tmp_path, enabled=False)
    result = asyncio.run(loop._do_work())
    assert result == {"status": "disabled"}


def test_do_work_returns_dict_when_enabled(tmp_path: Path) -> None:
    # When enabled, the skeleton still returns a dict — Tasks 12+ will
    # expand it with synthesis stats. The only contract here is that
    # it's a non-``disabled`` dict so the base-class status reporter can
    # publish it.
    loop = _loop(tmp_path)
    result = asyncio.run(loop._do_work())
    assert isinstance(result, dict)
    assert result.get("status") != "disabled"


# ---------------------------------------------------------------------------
# Task 11 — escape-signal reader
# ---------------------------------------------------------------------------


def _iso_now_offset(days: int) -> str:
    """Return an ISO-8601 UTC timestamp ``days`` ago (negative => past)."""
    return (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_list_escape_signals_parses_issues_into_dataclass(tmp_path: Path) -> None:
    recent = _iso_now_offset(-2)
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 101,
                "title": "diff-sanity missed dead config",
                "body": "plan vs diff drift",
                "updated_at": recent,
            },
            {
                "number": 102,
                "title": "scope-check let duplicate slip",
                "body": "no dup guard",
                "updated_at": recent,
            },
        ]
    )
    loop = _loop(tmp_path, prs=prs)

    signals = asyncio.run(loop._list_escape_signals())

    prs.list_issues_by_label.assert_awaited_once_with(DEFAULT_ESCAPE_LABEL)
    assert len(signals) == 2
    assert all(isinstance(sig, EscapeSignal) for sig in signals)
    assert [sig.issue_number for sig in signals] == [101, 102]
    assert signals[0].title == "diff-sanity missed dead config"
    assert signals[0].body == "plan vs diff drift"
    assert signals[0].updated_at == recent
    assert signals[0].label == DEFAULT_ESCAPE_LABEL


def test_list_escape_signals_filters_out_stale_issues(tmp_path: Path) -> None:
    # With a 30-day lookback, a 45-day-old issue must be dropped but a
    # 5-day-old one retained.
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 200,
                "title": "fresh",
                "body": "",
                "updated_at": _iso_now_offset(-5),
            },
            {
                "number": 201,
                "title": "stale",
                "body": "",
                "updated_at": _iso_now_offset(-45),
            },
        ]
    )
    loop = _loop(tmp_path, prs=prs)

    signals = asyncio.run(loop._list_escape_signals(lookback_days=30))

    assert [sig.issue_number for sig in signals] == [200]


def test_list_escape_signals_short_circuits_on_empty_list(tmp_path: Path) -> None:
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(return_value=[])
    loop = _loop(tmp_path, prs=prs)

    signals = asyncio.run(loop._list_escape_signals())

    assert signals == []
    prs.list_issues_by_label.assert_awaited_once()


def test_list_escape_signals_uses_custom_label(tmp_path: Path) -> None:
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(return_value=[])
    loop = _loop(tmp_path, prs=prs)

    asyncio.run(loop._list_escape_signals(label="skill-regression"))

    prs.list_issues_by_label.assert_awaited_once_with("skill-regression")


def test_list_escape_signals_skips_rows_without_number(tmp_path: Path) -> None:
    # Defensive parsing: gh's JSON contract is stable but any dict missing
    # ``number`` is useless for downstream synthesis and must be dropped
    # rather than propagated as an :class:`EscapeSignal(issue_number=0)`.
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 0,
                "title": "zero",
                "body": "",
                "updated_at": _iso_now_offset(-1),
            },
            {"title": "missing-number", "body": "", "updated_at": _iso_now_offset(-1)},
            {
                "number": 42,
                "title": "real",
                "body": "body",
                "updated_at": _iso_now_offset(-1),
            },
        ]
    )
    loop = _loop(tmp_path, prs=prs)

    signals = asyncio.run(loop._list_escape_signals())

    assert [sig.issue_number for sig in signals] == [42]


def test_list_escape_signals_drops_rows_with_unparseable_updated_at(
    tmp_path: Path,
) -> None:
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(
        return_value=[
            {"number": 1, "title": "bad ts", "body": "", "updated_at": "not-a-date"},
            {
                "number": 2,
                "title": "good ts",
                "body": "",
                "updated_at": _iso_now_offset(-1),
            },
        ]
    )
    loop = _loop(tmp_path, prs=prs)

    signals = asyncio.run(loop._list_escape_signals())

    assert [sig.issue_number for sig in signals] == [2]


def test_do_work_invokes_escape_signal_reader_when_enabled(tmp_path: Path) -> None:
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 7,
                "title": "escape",
                "body": "",
                "updated_at": _iso_now_offset(-1),
            },
        ]
    )
    loop = _loop(tmp_path, prs=prs)

    result = asyncio.run(loop._do_work())

    prs.list_issues_by_label.assert_awaited_once_with(DEFAULT_ESCAPE_LABEL)
    assert isinstance(result, dict)
    assert result.get("escape_issues_seen") == 1
    # Task 14 replaces the proposed/escalated stubs with cases_synthesized
    # /cases_validated; with a minimal body the signal is not synthesizable
    # and both counters stay zero.
    assert result.get("cases_synthesized") == 0
    assert result.get("cases_validated") == 0


def test_do_work_does_not_query_when_disabled(tmp_path: Path) -> None:
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(return_value=[])
    loop = _loop(tmp_path, prs=prs, enabled=False)

    result = asyncio.run(loop._do_work())

    assert result == {"status": "disabled"}
    prs.list_issues_by_label.assert_not_awaited()


def test_default_lookback_days_is_reasonable() -> None:
    # The reader's default must clearly prefer recency — anything over
    # ~90d stops being "recent escape signals" and starts being archival
    # noise. Task 15 will surface this as a tunable config field.
    assert 7 <= DEFAULT_LOOKBACK_DAYS <= 90


# ---------------------------------------------------------------------------
# Task 12 — in-process case synthesis
# ---------------------------------------------------------------------------


def _well_formed_signal_body(
    *,
    catcher: str = "diff-sanity",
    keyword: str = "renamed",
    before_path: str = "src/foo.py",
    before_body: str = "def compute_total():\n    return 1\n",
    after_path: str = "src/foo.py",
    after_body: str = "def compute_sum():\n    return 1\n",
    plan_text: str = "",
    readme_prose: str = "Symbol rename leaves callsite stale.",
) -> str:
    """Build an escape-issue body the synthesizer can parse cleanly."""
    parts = [
        readme_prose,
        "",
        f"Expected-Catcher: {catcher}",
        f"Keyword: {keyword}",
        "",
        f"```before:{before_path}",
        before_body.rstrip("\n"),
        "```",
        "",
        f"```after:{after_path}",
        after_body.rstrip("\n"),
        "```",
    ]
    if plan_text:
        parts.extend(["", "```plan", plan_text.rstrip("\n"), "```"])
    return "\n".join(parts)


def _signal(
    *,
    number: int = 501,
    title: str = "diff-sanity missed renamed callsite",
    body: str | None = None,
    updated_at: str | None = None,
) -> EscapeSignal:
    return EscapeSignal(
        issue_number=number,
        title=title,
        body=body if body is not None else _well_formed_signal_body(),
        updated_at=updated_at or _iso_now_offset(-1),
        label=DEFAULT_ESCAPE_LABEL,
    )


def test_synthesize_case_parses_wellformed_signal(tmp_path: Path) -> None:
    loop = _loop(tmp_path)

    case = loop._synthesize_case(_signal())

    assert isinstance(case, SynthesizedCase)
    assert case.issue_number == 501
    # Slug must be kebab-cased and derived from the title.
    assert case.slug == "diff-sanity-missed-renamed-callsite"
    assert case.expected_catcher == "diff-sanity"
    assert case.keyword == "renamed"
    assert case.before_files == {"src/foo.py": "def compute_total():\n    return 1\n"}
    assert case.after_files == {"src/foo.py": "def compute_sum():\n    return 1\n"}
    # README text retains the prose preamble so the harness has a home
    # for the human-readable explanation.
    assert "Symbol rename" in case.readme


def test_synthesize_case_slug_is_sanitized_and_bounded(tmp_path: Path) -> None:
    # Weird punctuation, mixed case, and overlength titles must still
    # produce a filesystem-safe kebab slug.
    loop = _loop(tmp_path)
    messy_title = "Diff-Sanity: let THROUGH accidental `rm -rf`!!  " + "x" * 200
    case = loop._synthesize_case(_signal(title=messy_title))

    assert case is not None
    # Only [a-z0-9-] and no leading/trailing dashes, length capped.
    assert case.slug == case.slug.lower()
    assert all(c.isalnum() or c == "-" for c in case.slug)
    assert not case.slug.startswith("-") and not case.slug.endswith("-")
    assert 1 <= len(case.slug) <= 64


def test_synthesize_case_accepts_every_registered_catcher(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    for catcher in ("diff-sanity", "scope-check", "test-adequacy", "plan-compliance"):
        body = _well_formed_signal_body(catcher=catcher)
        case = loop._synthesize_case(_signal(body=body))
        assert case is not None, catcher
        assert case.expected_catcher == catcher


def test_synthesize_case_returns_none_when_catcher_missing(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    body = "\n".join(
        [
            "Expected-Catcher: ",  # blank
            "Keyword: whatever",
            "```before:src/x.py",
            "a = 1",
            "```",
            "```after:src/x.py",
            "a = 2",
            "```",
        ]
    )
    assert loop._synthesize_case(_signal(body=body)) is None


def test_synthesize_case_returns_none_when_catcher_unknown(tmp_path: Path) -> None:
    # Catcher must be one of the registered skills; an unknown value
    # is surfaced as a parse failure (return None) rather than a crash.
    loop = _loop(tmp_path)
    body = _well_formed_signal_body(catcher="ghost-skill")
    assert loop._synthesize_case(_signal(body=body)) is None


def test_synthesize_case_returns_none_when_keyword_missing(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    body = "\n".join(
        [
            "Expected-Catcher: diff-sanity",
            "```before:src/x.py",
            "a = 1",
            "```",
            "```after:src/x.py",
            "a = 2",
            "```",
        ]
    )
    assert loop._synthesize_case(_signal(body=body)) is None


def test_synthesize_case_returns_none_when_no_before_block(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    body = "\n".join(
        [
            "Expected-Catcher: diff-sanity",
            "Keyword: anything",
            "```after:src/x.py",
            "a = 2",
            "```",
        ]
    )
    assert loop._synthesize_case(_signal(body=body)) is None


def test_synthesize_case_returns_none_when_no_after_block(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    body = "\n".join(
        [
            "Expected-Catcher: diff-sanity",
            "Keyword: anything",
            "```before:src/x.py",
            "a = 1",
            "```",
        ]
    )
    assert loop._synthesize_case(_signal(body=body)) is None


def test_synthesize_case_returns_none_on_empty_body(tmp_path: Path) -> None:
    # Minimal signals (no body at all) must be skipped — never crash the loop.
    loop = _loop(tmp_path)
    assert loop._synthesize_case(_signal(body="")) is None


def test_synthesize_case_captures_plan_text_when_present(tmp_path: Path) -> None:
    # scope-check / plan-compliance need a plan_text — the synthesizer
    # extracts it from a ```plan ... ``` block when present.
    loop = _loop(tmp_path)
    body = _well_formed_signal_body(
        catcher="scope-check",
        plan_text="## Plan\n- touch src/foo.py\n",
    )
    case = loop._synthesize_case(_signal(body=body))

    assert case is not None
    assert "touch src/foo.py" in case.plan_text


# ---------------------------------------------------------------------------
# Task 13 — three-gate self-validation
# ---------------------------------------------------------------------------


def _case(
    *,
    catcher: str = "diff-sanity",
    keyword: str = "renamed",
    before_files: dict[str, str] | None = None,
    after_files: dict[str, str] | None = None,
    plan_text: str = "",
) -> SynthesizedCase:
    before = (
        before_files
        if before_files is not None
        else {
            "src/foo.py": "def compute_total():\n    return 1\n",
        }
    )
    after = (
        after_files
        if after_files is not None
        else {
            "src/foo.py": "def compute_sum():\n    return 1\n",
        }
    )
    return SynthesizedCase(
        issue_number=77,
        slug="synthetic-case",
        expected_catcher=catcher,
        keyword=keyword,
        before_files=before,
        after_files=after,
        readme="Reproducer.",
        plan_text=plan_text,
    )


def test_validate_case_passes_when_all_three_gates_green(tmp_path: Path) -> None:
    loop = _loop(tmp_path)

    result = loop._validate_case(_case())

    assert isinstance(result, ValidationResult)
    assert result.ok is True, result.reason
    assert result.failing_gate == ""


def test_validate_case_fails_harness_accepts_on_empty_diff(tmp_path: Path) -> None:
    # Identical before/after yields an empty diff — the harness rejects
    # it with the same assertion used in test_adversarial_corpus.test_case.
    loop = _loop(tmp_path)
    identical = {"src/foo.py": "x = 1\n"}
    case = _case(before_files=identical, after_files=identical)

    result = loop._validate_case(case)

    assert result.ok is False
    assert result.failing_gate == "harness_accepts"
    assert "diff" in result.reason.lower()


def test_validate_case_fails_expected_catcher_trips_when_keyword_absent(
    tmp_path: Path,
) -> None:
    # Keyword convention (harness `_read_keyword`): must appear in the
    # catcher's parsed summary. Pick a keyword that cannot appear in our
    # deterministic RETRY fixture.
    loop = _loop(tmp_path)
    case = _case(keyword="nonexistent-unique-token-xyz")

    # Force the fixture builder path by overriding it with one that
    # deliberately omits the keyword from SUMMARY.
    original = loop._fixture_transcript_for

    def stripped(c: SynthesizedCase, skill_name: str) -> str:
        return original(c, skill_name).replace(c.keyword, "DIFFERENT")

    loop._fixture_transcript_for = stripped  # type: ignore[method-assign]

    result = loop._validate_case(case)

    assert result.ok is False
    assert result.failing_gate == "expected_catcher_trips"


def test_validate_case_fails_unambiguous_on_cross_catcher_trip(
    tmp_path: Path,
) -> None:
    # If the synthesized fixture trips BOTH diff-sanity AND test-adequacy,
    # the case is ambiguous and gate (c) must reject it.
    loop = _loop(tmp_path)
    case = _case(catcher="diff-sanity")

    original = loop._fixture_transcript_for

    def poisoned(c: SynthesizedCase, skill_name: str) -> str:
        base = original(c, skill_name)
        # Force a second catcher's marker in as well.
        return (
            base + "\n" + f"TEST_ADEQUACY_RESULT: RETRY\nSUMMARY: {c.keyword} — extra\n"
        )

    loop._fixture_transcript_for = poisoned  # type: ignore[method-assign]

    result = loop._validate_case(case)

    assert result.ok is False
    assert result.failing_gate == "unambiguous"
    assert "test-adequacy" in result.reason


def test_validate_case_scope_check_uses_plan_text(tmp_path: Path) -> None:
    # scope-check's prompt_builder auto-passes when plan_text is empty —
    # so a scope-check case without a plan_text must still produce the
    # catcher-trip via the fixture (gate b handles this deterministically).
    # This test confirms that scope-check with a plan_text present
    # validates cleanly.
    loop = _loop(tmp_path)
    case = _case(
        catcher="scope-check",
        keyword="scope",
        plan_text="## Plan\n- touch src/foo.py\n",
    )

    result = loop._validate_case(case)

    assert result.ok is True, result.reason


# ---------------------------------------------------------------------------
# Task 14 — _do_work wiring
# ---------------------------------------------------------------------------


def test_do_work_synthesizes_and_validates_parseable_signal(tmp_path: Path) -> None:
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 909,
                "title": "diff-sanity missed renamed symbol",
                "body": _well_formed_signal_body(),
                "updated_at": _iso_now_offset(-1),
            },
        ]
    )
    loop = _loop(tmp_path, prs=prs)

    result = asyncio.run(loop._do_work())

    assert result.get("escape_issues_seen") == 1
    assert result.get("cases_synthesized") == 1
    assert result.get("cases_validated") == 1


def test_do_work_counts_synthesis_failures_separately(tmp_path: Path) -> None:
    # One parseable signal + one unparseable (empty body) => 2 seen,
    # 1 synthesized, 1 validated. The loop must not crash on the bad row.
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 1,
                "title": "diff-sanity escape",
                "body": _well_formed_signal_body(),
                "updated_at": _iso_now_offset(-1),
            },
            {
                "number": 2,
                "title": "unparseable escape",
                "body": "",
                "updated_at": _iso_now_offset(-1),
            },
        ]
    )
    loop = _loop(tmp_path, prs=prs)

    result = asyncio.run(loop._do_work())

    assert result.get("escape_issues_seen") == 2
    assert result.get("cases_synthesized") == 1
    assert result.get("cases_validated") == 1


def test_do_work_counts_validation_failures_separately(tmp_path: Path) -> None:
    # A synthesized but invalid case (identical before/after => empty diff)
    # must count as synthesized but not validated.
    identical_block = "```before:src/a.py\na = 1\n```\n```after:src/a.py\na = 1\n```\n"
    bad_body = (
        "Repro.\n\n"
        "Expected-Catcher: diff-sanity\n"
        "Keyword: anything\n\n" + identical_block
    )
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 10,
                "title": "empty-diff escape",
                "body": bad_body,
                "updated_at": _iso_now_offset(-1),
            },
        ]
    )
    loop = _loop(tmp_path, prs=prs)

    result = asyncio.run(loop._do_work())

    assert result.get("escape_issues_seen") == 1
    assert result.get("cases_synthesized") == 1
    assert result.get("cases_validated") == 0
