"""Regression test for issue #6511.

Bug: bare ``except Exception: pass`` blocks in ``health_monitor_loop.py``
and ``orchestrator.py`` silently swallow errors in non-trivial operations,
leaving operators blind to systematic failures.

These tests assert the CORRECT (post-fix) behaviour: every caught exception
in these blocks must produce at least a ``debug``-level log message.  They
are RED against the current buggy code because the bare ``pass`` emits
nothing.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from health_monitor_loop import compute_trend_metrics  # noqa: E402

HEALTH_LOGGER = "hydraflow.health_monitor_loop"
ORCHESTRATOR_LOGGER = "hydraflow.orchestrator"


# ---------------------------------------------------------------------------
# 1. compute_trend_metrics — malformed outcomes.jsonl line (L182-183)
# ---------------------------------------------------------------------------


class TestMalformedOutcomesLineLogging:
    """When outcomes.jsonl contains a non-JSON line, the inner per-line
    except block must log a debug message so operators can see that
    lines are being skipped.

    Currently the code does ``except Exception: pass`` (line 182-183),
    so no log is emitted — this test is RED.
    """

    @pytest.mark.xfail(reason="Regression for issue #6511 — fix not yet landed", strict=False)
    def test_malformed_outcomes_line_emits_log(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Arrange
        outcomes = tmp_path / "outcomes.jsonl"
        outcomes.write_text(
            'NOT VALID JSON\n{"outcome": "success"}\n',
            encoding="utf-8",
        )
        scores = tmp_path / "item_scores.json"
        failures = tmp_path / "harness_failures.jsonl"

        # Act
        with caplog.at_level(logging.DEBUG, logger=HEALTH_LOGGER):
            result = compute_trend_metrics(outcomes, scores, failures)

        # Assert — the valid line should still be counted
        assert result.first_pass_rate == 1.0
        assert result.total_outcomes == 1

        # Assert — the malformed line must produce a log record
        health_records = [r for r in caplog.records if r.name == HEALTH_LOGGER]
        assert any(
            "malformed" in r.message.lower() or "skip" in r.message.lower()
            for r in health_records
        ), (
            f"Expected a log message about the malformed outcomes line, "
            f"but got: {[r.message for r in health_records]}"
        )


# ---------------------------------------------------------------------------
# 2. compute_trend_metrics — corrupt item_scores.json (L205-206)
# ---------------------------------------------------------------------------


class TestCorruptItemScoresLogging:
    """When item_scores.json contains invalid JSON, the outer except block
    must log a debug message.

    Currently ``except Exception: pass`` (line 205-206) — RED.
    """

    @pytest.mark.xfail(reason="Regression for issue #6511 — fix not yet landed", strict=False)
    def test_corrupt_scores_file_emits_log(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Arrange
        outcomes = tmp_path / "outcomes.jsonl"
        scores = tmp_path / "item_scores.json"
        scores.write_text("THIS IS NOT JSON", encoding="utf-8")
        failures = tmp_path / "harness_failures.jsonl"

        # Act
        with caplog.at_level(logging.DEBUG, logger=HEALTH_LOGGER):
            result = compute_trend_metrics(outcomes, scores, failures)

        # Assert — metrics fall back to defaults
        assert result.avg_memory_score == 0.0

        # Assert — a log record must be emitted
        health_records = [r for r in caplog.records if r.name == HEALTH_LOGGER]
        assert any(
            "item_scores" in r.message.lower()
            or "score" in r.message.lower()
            or "malformed" in r.message.lower()
            for r in health_records
        ), (
            f"Expected a log message about the corrupt item_scores.json, "
            f"but got: {[r.message for r in health_records]}"
        )


# ---------------------------------------------------------------------------
# 3. orchestrator — Sentry set_tag failure (L710-711)
# ---------------------------------------------------------------------------


class TestSentrySetTagFailureLogging:
    """When ``sentry_sdk.set_tag`` raises, the orchestrator must log
    the failure at debug level.

    Currently ``except Exception: pass`` (line 710-711) — RED.
    """

    @pytest.mark.xfail(reason="Regression for issue #6511 — fix not yet landed", strict=False)
    def test_sentry_set_tag_failure_emits_log(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # We test the pattern directly by importing orchestrator and
        # exercising the try/except around set_tag.  Since the block
        # is inside ``_run()``, we replicate the exact code path with
        # a mock.
        mock_sentry = MagicMock()
        mock_sentry.set_tag.side_effect = RuntimeError("sentry unavailable")

        with caplog.at_level(logging.DEBUG, logger=ORCHESTRATOR_LOGGER):
            # Replicate the orchestrator's try/except block (L706-711)
            try:
                mock_sentry.set_tag("hydraflow.repo", "test-repo")
            except Exception:
                # This is what the FIXED code should do — log the error.
                # The current code just does ``pass``.
                pass

        # The orchestrator itself doesn't log — verify by importing
        # the module and checking that its except block would log.
        # Since we can't easily call _run() in isolation, we inspect
        # the source to confirm no logging call exists.
        import inspect

        import orchestrator as orch_mod

        source = inspect.getsource(orch_mod)

        # Find the sentry set_tag try block
        # The fix should add a logger call in the except block
        idx = source.find('_sentry.set_tag("hydraflow.repo"')
        assert idx != -1, "Could not find sentry set_tag call in orchestrator"

        # Extract the except block that follows
        except_start = source.find("except Exception:", idx)
        assert except_start != -1

        # Get the next ~200 chars after 'except Exception:'
        block = source[except_start : except_start + 200]

        # The fixed code must contain a logger call, not bare pass
        assert "logger" in block or "logging" in block, (
            f"orchestrator.py sentry set_tag except block has no logging. "
            f"Block content: {block!r}"
        )


# ---------------------------------------------------------------------------
# 4. compute_trend_metrics — malformed harness_failures.jsonl line (L226-227)
# ---------------------------------------------------------------------------


class TestMalformedFailuresLineLogging:
    """When harness_failures.jsonl has a malformed JSON line, the inner
    per-line except must log.

    Currently ``except Exception: pass`` (line 226-227) — RED.
    """

    @pytest.mark.xfail(reason="Regression for issue #6511 — fix not yet landed", strict=False)
    def test_malformed_failures_line_emits_log(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Arrange
        outcomes = tmp_path / "outcomes.jsonl"
        scores = tmp_path / "item_scores.json"
        failures = tmp_path / "harness_failures.jsonl"
        failures.write_text(
            'NOT VALID JSON\n{"category": "review_rejection"}\n',
            encoding="utf-8",
        )

        # Act
        with caplog.at_level(logging.DEBUG, logger=HEALTH_LOGGER):
            result = compute_trend_metrics(outcomes, scores, failures)

        # Assert — valid line still parsed
        assert result.surprise_rate > 0.0

        # Assert — malformed line must produce log
        health_records = [r for r in caplog.records if r.name == HEALTH_LOGGER]
        assert any(
            "malformed" in r.message.lower() or "skip" in r.message.lower()
            for r in health_records
        ), (
            f"Expected a log message about the malformed failures line, "
            f"but got: {[r.message for r in health_records]}"
        )


# ---------------------------------------------------------------------------
# 5. Source inspection — all except-pass blocks must have logging
# ---------------------------------------------------------------------------


class TestBareExceptPassBlocksHaveLogging:
    """Static check: every ``except Exception:`` block in the two files
    must contain a logging call, not a bare ``pass``.

    This is a meta-test that inspects the source code directly.  It is
    RED when any except-Exception block contains only ``pass`` with no
    ``logger.`` call.
    """

    @staticmethod
    def _find_bare_except_pass_blocks(source: str) -> list[tuple[int, str]]:
        """Return (line_number, context) for except-Exception blocks with bare pass."""
        lines = source.splitlines()
        violations: list[tuple[int, str]] = []
        i = 0
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith("except Exception") and ":" in stripped:
                # Collect the block body (indented lines after except)
                except_line = i
                indent = len(lines[i]) - len(lines[i].lstrip())
                block_lines: list[str] = []
                j = i + 1
                while j < len(lines):
                    if not lines[j].strip():
                        j += 1
                        continue
                    line_indent = len(lines[j]) - len(lines[j].lstrip())
                    if line_indent <= indent:
                        break
                    block_lines.append(lines[j].strip())
                    j += 1

                # Check if block has only pass/comments, no logger call
                has_logging = any(
                    "logger." in bl or "logging." in bl for bl in block_lines
                )
                has_only_pass = all(
                    bl == "pass" or bl.startswith("#") or bl.startswith("# noqa")
                    for bl in block_lines
                    if bl  # skip empty
                )

                if has_only_pass and not has_logging:
                    context = lines[except_line].strip()
                    violations.append((except_line + 1, context))

                i = j
            else:
                i += 1
        return violations

    @pytest.mark.xfail(reason="Regression for issue #6511 — fix not yet landed", strict=False)
    def test_health_monitor_no_bare_except_pass(self) -> None:
        """health_monitor_loop.py must not have bare except-pass blocks."""
        import inspect

        import health_monitor_loop

        source = inspect.getsource(health_monitor_loop)
        violations = self._find_bare_except_pass_blocks(source)

        assert not violations, (
            f"health_monitor_loop.py has {len(violations)} bare except-pass block(s) "
            f"without logging: {violations}"
        )

    @pytest.mark.xfail(reason="Regression for issue #6511 — fix not yet landed", strict=False)
    def test_orchestrator_no_bare_except_pass(self) -> None:
        """orchestrator.py must not have bare except-pass blocks."""
        import inspect

        import orchestrator

        source = inspect.getsource(orchestrator)
        violations = self._find_bare_except_pass_blocks(source)

        assert not violations, (
            f"orchestrator.py has {len(violations)} bare except-pass block(s) "
            f"without logging: {violations}"
        )
