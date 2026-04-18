"""Regression test for issue #6984.

``detect_knowledge_gaps`` accepts an ``overlap_threshold`` parameter but never
forwards it to the internal helper ``_failure_is_addressed``.  The helper
hardcodes ``_GAP_OVERLAP_THRESHOLD`` (0.30) instead, so callers cannot tune
sensitivity at runtime — the parameter is dead API surface.

Strategy
--------
Create a failure whose ``details`` text shares moderate word overlap (~40 %)
with a memory text.  Under the default threshold of 0.30, the failure is
considered "addressed" and filtered out.  When a caller explicitly passes
``overlap_threshold=0.99`` the failure should be treated as *unaddressed*
(because 0.40 < 0.99) and therefore appear as a ``KnowledgeGap``.

If the parameter is silently ignored, both calls return the same result — the
test fails.
"""

from __future__ import annotations

import pytest

import json
from pathlib import Path

from memory_scoring import detect_knowledge_gaps


def _write_failures(tmp_path: Path, records: list[dict]) -> Path:
    """Write failure records to a JSONL file and return its path."""
    fp = tmp_path / "harness_failures.jsonl"
    fp.write_text(
        "\n".join(json.dumps(r) for r in records),
        encoding="utf-8",
    )
    return fp


class TestOverlapThresholdIsRespected:
    """overlap_threshold must actually control the overlap comparison."""

    # Tokens deliberately arranged so word overlap ≈ 40 %:
    #   failure words: {"the", "deploy", "failed", "because", "lint", "errors", "blocked", "merge"}
    #   memory words:  {"the", "deploy", "failed", "due", "to", "network", "timeout", "issues"}
    #   intersection:  {"the", "deploy", "failed"}  → 3
    #   union:         {"the", "deploy", "failed", "because", "lint", "errors",
    #                   "blocked", "merge", "due", "to", "network", "timeout", "issues"} → 13
    #   overlap = 3/13 ≈ 0.23 — too low; need higher overlap.  Adjust texts.

    # Revised for ~45 % overlap:
    #   failure: "the deploy script failed with lint errors on the merge branch"
    #   memory:  "the deploy script failed with timeout errors on the staging branch"
    #   failure tokens: {the, deploy, script, failed, with, lint, errors, on, merge, branch}  → 10
    #   memory tokens:  {the, deploy, script, failed, with, timeout, errors, on, staging, branch} → 10
    #   intersection: {the, deploy, script, failed, with, errors, on, branch} → 8
    #   union:        {the, deploy, script, failed, with, lint, timeout, errors, on, merge, staging, branch} → 12
    #   overlap = 8/12 ≈ 0.667  — comfortably above default 0.30

    FAILURE_DETAILS = "the deploy script failed with lint errors on the merge branch"
    MEMORY_TEXT = "the deploy script failed with timeout errors on the staging branch"

    FAILURE_RECORD = {
        "issue_number": 1,
        "pr_number": 0,
        "timestamp": "2026-04-10T00:00:00",
        "category": "quality_gate",
        "subcategories": [],
        "details": FAILURE_DETAILS,
    }

    def test_default_threshold_filters_high_overlap_failure(
        self, tmp_path: Path
    ) -> None:
        """Sanity check: with default threshold (0.30), the failure IS addressed."""
        fp = _write_failures(tmp_path, [self.FAILURE_RECORD] * 3)
        gaps = detect_knowledge_gaps(
            fp,
            [self.MEMORY_TEXT],
            frequency_threshold=1,
        )
        # Overlap ≈ 0.667 > 0.30 → failure is addressed → no gap reported
        assert gaps == [], f"Expected no gaps at default threshold, got {gaps!r}"

    @pytest.mark.xfail(reason="Regression for issue #6984 — fix not yet landed", strict=False)
    def test_high_threshold_should_surface_gap(self, tmp_path: Path) -> None:
        """With overlap_threshold=0.99, the ~67 % overlap should NOT filter the failure.

        BUG: Because overlap_threshold is never forwarded, the hardcoded 0.30 is
        used and the failure is still filtered — so this returns no gaps when it
        should return one.
        """
        fp = _write_failures(tmp_path, [self.FAILURE_RECORD] * 3)
        gaps = detect_knowledge_gaps(
            fp,
            [self.MEMORY_TEXT],
            frequency_threshold=1,
            overlap_threshold=0.99,
        )
        # With threshold=0.99, overlap 0.667 < 0.99 → NOT addressed → gap expected
        assert len(gaps) == 1, (
            f"Expected 1 knowledge gap when overlap_threshold=0.99 "
            f"(overlap ≈ 0.667 < 0.99 means failure is unaddressed), "
            f"but got {len(gaps)} gaps. "
            f"This confirms overlap_threshold is silently ignored (issue #6984)."
        )
        assert gaps[0].failure_category == "quality_gate"
