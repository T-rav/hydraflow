"""Deterministic signal extraction from gathered evidence (§2).

Signals quantify what went wrong across a window of issues. They are the only
grounding the LLM stage is permitted, and every signal must carry evidence text
that the §4 validator can resolve a finding's excerpt against.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models import (  # noqa: E402
    SkillResultRecord,
    SubprocessTrace,
    ToolCallSpan,
    TraceTokenStats,
    TraceToolProfile,
)
from retro_evidence import RetroEvidence  # noqa: E402
from retro_signals import extract  # noqa: E402

TOKENS = TraceTokenStats(
    prompt_tokens=0,
    completion_tokens=0,
    cache_read_tokens=0,
    cache_creation_tokens=0,
    cache_hit_rate=0.0,
)


def _span(name: str, *, error: str | None, succeeded: bool, summary: str = "x"):
    return ToolCallSpan(
        tool_name=name,
        started_at="2026-08-31T00:00:00+00:00",
        duration_ms=1,
        input_summary=summary,
        succeeded=succeeded,
        error=error,
        tool_use_id=None,
    )


def _trace(
    issue: int, *, phase="implement", spans=(), crashed=False, error=None, skills=()
):
    return SubprocessTrace(
        issue_number=issue,
        phase=phase,
        source="implementer",
        run_id=1,
        subprocess_idx=0,
        backend="claude",
        started_at="2026-08-31T00:00:00+00:00",
        ended_at="2026-08-31T00:01:00+00:00",
        success=not crashed,
        crashed=crashed,
        error=error,
        tokens=TOKENS,
        tools=TraceToolProfile(tool_counts={}, tool_errors={}, total_invocations=0),
        tool_calls=list(spans),
        skill_results=list(skills),
        turn_count=1,
        inference_count=1,
    )


def _bundle(issue: int, traces=(), transcripts=None):
    return RetroEvidence(
        issue_number=issue, traces=list(traces), transcripts=transcripts or {}
    )


def _families(signals, family):
    return [s for s in signals if s.family == family]


class TestToolErrorClusters:
    def test_same_error_across_issues_is_one_signal_counting_both(self):
        span = _span("Bash", error="make: *** [quality] Error 1", succeeded=False)
        signals = extract(
            [
                _bundle(1, [_trace(1, spans=[span])]),
                _bundle(2, [_trace(2, spans=[span])]),
            ]
        )

        errors = _families(signals, "tool_error")
        assert len(errors) == 1
        assert errors[0].count == 2
        assert sorted(errors[0].issues) == [1, 2]

    def test_errors_differing_only_in_paths_cluster_together(self):
        signals = extract(
            [
                _bundle(
                    1,
                    [
                        _trace(
                            1,
                            spans=[
                                _span(
                                    "Read",
                                    error="no such file src/a.py",
                                    succeeded=False,
                                )
                            ],
                        )
                    ],
                ),
                _bundle(
                    2,
                    [
                        _trace(
                            2,
                            spans=[
                                _span(
                                    "Read",
                                    error="no such file src/b.py",
                                    succeeded=False,
                                )
                            ],
                        )
                    ],
                ),
            ]
        )

        assert len(_families(signals, "tool_error")) == 1

    def test_signal_carries_the_literal_error_text_for_validation(self):
        signals = extract(
            [
                _bundle(
                    1,
                    [
                        _trace(
                            1,
                            spans=[
                                _span(
                                    "Bash",
                                    error="make: *** [quality] Error 1",
                                    succeeded=False,
                                )
                            ],
                        )
                    ],
                )
            ]
        )

        excerpts = [e.excerpt for e in _families(signals, "tool_error")[0].evidence]
        assert any("make: *** [quality] Error 1" in x for x in excerpts)


class TestSignalsNeverKeyOnSucceeded:
    """Codex spans end succeeded=False, error=None — never closed, not failed.

    Keying on `succeeded` would score every Codex tool call as a failure.
    """

    def test_codex_shaped_span_produces_no_tool_error_signal(self):
        codex_span = _span("shell", error=None, succeeded=False)

        signals = extract([_bundle(1, [_trace(1, spans=[codex_span])])])

        assert _families(signals, "tool_error") == []

    def test_a_real_error_on_an_unclosed_span_still_counts(self):
        signals = extract(
            [
                _bundle(
                    1, [_trace(1, spans=[_span("Bash", error="boom", succeeded=False)])]
                )
            ]
        )

        assert len(_families(signals, "tool_error")) == 1


class TestCrashSignatures:
    def test_crashed_subprocess_becomes_a_signal(self):
        signals = extract(
            [_bundle(1, [_trace(1, crashed=True, error="connection reset")])]
        )

        crashes = _families(signals, "crash")
        assert len(crashes) == 1
        assert crashes[0].count == 1

    def test_uncrashed_subprocess_produces_none(self):
        signals = extract([_bundle(1, [_trace(1)])])

        assert _families(signals, "crash") == []


class TestSkillFailures:
    def test_failed_skill_becomes_a_signal(self):
        skill = SkillResultRecord(
            skill_name="test-driven-development",
            passed=False,
            attempts=3,
            duration_seconds=1.0,
            blocking=True,
        )

        signals = extract([_bundle(1, [_trace(1, skills=[skill])])])

        failures = _families(signals, "skill_failure")
        assert len(failures) == 1
        assert "test-driven-development" in failures[0].signature

    def test_skill_failure_carries_no_excerpt(self):
        """SkillResultRecord has no error text — so it can never ground a BUGFIX."""
        skill = SkillResultRecord(
            skill_name="x",
            passed=False,
            attempts=1,
            duration_seconds=1.0,
            blocking=False,
        )

        signals = extract([_bundle(1, [_trace(1, skills=[skill])])])

        assert _families(signals, "skill_failure")[0].evidence == []


class TestToolThrash:
    def test_repeated_identical_tool_input_is_a_signal(self):
        spans = [
            _span("Edit", error=None, succeeded=True, summary="same file")
            for _ in range(5)
        ]

        signals = extract([_bundle(1, [_trace(1, spans=spans)])])

        thrash = _families(signals, "tool_thrash")
        assert len(thrash) == 1
        assert thrash[0].count == 5

    def test_varied_inputs_are_not_thrash(self):
        spans = [
            _span("Edit", error=None, succeeded=True, summary=f"file {i}")
            for i in range(5)
        ]

        signals = extract([_bundle(1, [_trace(1, spans=spans)])])

        assert _families(signals, "tool_thrash") == []


class TestSignalIdentity:
    def test_ids_are_unique_across_signals(self):
        signals = extract(
            [
                _bundle(
                    1,
                    [
                        _trace(
                            1,
                            spans=[
                                _span("Bash", error="a", succeeded=False),
                                _span("Read", error="b", succeeded=False),
                            ],
                            crashed=True,
                            error="c",
                        )
                    ],
                )
            ]
        )

        ids = [s.id for s in signals]
        assert len(ids) == len(set(ids))

    def test_id_is_stable_across_runs(self):
        bundle = _bundle(
            1, [_trace(1, spans=[_span("Bash", error="boom", succeeded=False)])]
        )

        assert [s.id for s in extract([bundle])] == [s.id for s in extract([bundle])]


class TestEmptyInput:
    def test_no_evidence_yields_no_signals(self):
        assert extract([]) == []
        assert extract([_bundle(1)]) == []
