"""#11942 — the trace's error summary dropped the newest stream errors.

Upheld sampled re-audit of PR #11887. The two halves of the cap disagreed:

* in memory, ``del self.stream_errors[:-_MAX_STREAM_ERRORS]`` keeps the most
  RECENT entries, on the stated grounds that "the newest are the diagnostic
  ones" (`trace_collector` line 43);
* on write, ``"; ".join(errors)[:_MAX_ERROR_CHARS]`` is a FRONT slice, keeping
  the EARLIEST and silently dropping the newest.

`SubprocessTrace` has no `stream_errors` field, so `error` is the only place
these reach disk. A run that died on an auth failure after three noisy warnings
persisted the warnings and not the reason — in the field a retrospective reads.

No existing test exercised more than one error under the budget, which is why
an ordering bug in a one-line slice survived review.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers import ConfigFactory
from trace_collector import _MAX_ERROR_CHARS, TraceCollector, _newest_errors_within


def _msg(tag: str, size: int = 200) -> str:
    return f"{tag}: " + "x" * size


class TestTheNewestSurvives:
    def test_the_terminal_error_is_kept_when_the_budget_overflows(self) -> None:
        errors = [_msg(f"e{i}") for i in range(1, 5)]

        summary = _newest_errors_within(errors, _MAX_ERROR_CHARS)

        assert "e4" in summary

    def test_the_stale_earliest_error_is_the_one_dropped(self) -> None:
        errors = [_msg(f"e{i}") for i in range(1, 5)]

        summary = _newest_errors_within(errors, _MAX_ERROR_CHARS)

        assert "e1" not in summary

    def test_the_newest_alone_survives_a_budget_it_exceeds(self) -> None:
        # A summary that drops the reason a run died is worse than a short one.
        summary = _newest_errors_within([_msg("old"), _msg("terminal")], 60)

        assert summary.startswith("terminal: ")

    def test_older_errors_are_never_sliced_mid_message(self) -> None:
        # Whole messages or none: half a stack trace reads as a different error.
        errors = ["a" * 100, "b" * 100, "c" * 100]

        summary = _newest_errors_within(errors, 210)

        assert summary == "b" * 100 + "; " + "c" * 100


class TestItStillReadsAsASequence:
    def test_everything_that_fits_is_rendered_oldest_first(self) -> None:
        summary = _newest_errors_within(["first", "second", "third"], 100)

        assert summary == "first; second; third"

    def test_the_result_stays_within_budget(self) -> None:
        errors = [_msg(f"e{i}") for i in range(1, 9)]

        assert len(_newest_errors_within(errors, _MAX_ERROR_CHARS)) <= _MAX_ERROR_CHARS


class TestTheEmptyCases:
    @pytest.mark.parametrize(
        ("errors", "expected"),
        [
            pytest.param([], None, id="no-errors"),
            pytest.param([""], None, id="one-empty-string"),
        ],
    )
    def test_nothing_to_report_stays_none(
        self, errors: list[str], expected: None
    ) -> None:
        # `error` is Optional on the model; "" would read as an error that
        # happened and had no text, which is a different claim from "none".
        assert _newest_errors_within(errors, _MAX_ERROR_CHARS) is expected


def test_a_single_capped_error_always_fits_the_budget() -> None:
    """The two constants are related, and the relation is load-bearing.

    Appends cap each message at ``_MAX_ERROR_CHARS`` and the summary budget is
    the same constant, so the newest message always fits whole. If someone
    lowers the budget without lowering the append cap, the newest is truncated
    rather than lost — still correct, and this states the dependency so the
    change is a decision rather than a surprise.
    """
    summary = _newest_errors_within(["z" * _MAX_ERROR_CHARS], _MAX_ERROR_CHARS)

    assert len(summary) == _MAX_ERROR_CHARS


class TestThroughTheRealCollector:
    """The helper is only half the fix — the call site is the other half.

    Pinning `_newest_errors_within` alone left a hole a mutation found: putting
    the old `"; ".join(...)[:budget]` back at the call site kept every unit test
    above green, because none of them reached `finalize()`. The audit finding
    was about `SubprocessTrace.error`, the only place stream errors reach disk,
    so that is what these assert.
    """

    @staticmethod
    def _collector(tmp_path: Path) -> TraceCollector:
        config = ConfigFactory.create()
        config.data_root = tmp_path
        return TraceCollector(
            issue_number=42,
            phase="implement",
            source="implementer",
            subprocess_idx=0,
            run_id=1,
            config=config,
            event_bus=None,
        )

    def _trace_error(self, tmp_path: Path, messages: list[str]) -> str:
        collector = self._collector(tmp_path)
        for message in messages:
            collector.record(json.dumps({"type": "error", "message": message}))
        trace = collector.finalize(success=False)
        assert trace is not None
        return trace.error or ""

    def test_the_persisted_error_carries_the_terminal_failure(
        self, tmp_path: Path
    ) -> None:
        error = self._trace_error(
            tmp_path, [_msg(f"e{i}") for i in range(1, 5)]
        )

        assert "e4" in error

    def test_the_persisted_error_drops_the_stale_earliest(
        self, tmp_path: Path
    ) -> None:
        error = self._trace_error(
            tmp_path, [_msg(f"e{i}") for i in range(1, 5)]
        )

        assert "e1" not in error

    def test_a_single_error_still_reaches_disk_intact(self, tmp_path: Path) -> None:
        error = self._trace_error(tmp_path, ["connection reset by peer"])

        assert error == "connection reset by peer"
