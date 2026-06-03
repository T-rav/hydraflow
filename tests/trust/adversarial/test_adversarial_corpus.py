"""Adversarial corpus harness — iterates tests/trust/adversarial/cases/*.

Each case directory contains:
  - before/ / after/        minimal pre/post-diff repo subset
  - expected_catcher.txt     one of the registered skills' names, or "none"
  - README.md                describes the bug + names a required `Keyword:`
  - expected_transcript.txt  (optional) canned LLM transcript fixture

The per-case evaluation logic lives in :mod:`corpus_runner` so it is shared
with the ``FORMAT=json`` producer consumed by ``SkillPromptEvalLoop``. This
harness asserts the expected catcher still flags each case (status ``PASS``);
the loop diffs ``PASS -> FAIL`` over time to detect skill-prompt drift.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from corpus_runner import (  # noqa: E402
    MissingTranscriptError,
    discover_cases,
    evaluate_case,
)


@pytest.mark.parametrize(
    "case_dir",
    discover_cases(),
    ids=lambda p: p.name,
)
def test_case(case_dir: Path) -> None:
    """Each case's expected catcher must still flag it (no PASS->FAIL drift)."""
    live = os.environ.get("HYDRAFLOW_TRUST_ADVERSARIAL_LIVE") == "1"
    try:
        result = evaluate_case(case_dir, live=live, strict=True)
    except MissingTranscriptError as exc:
        pytest.fail(str(exc))

    assert result["status"] == "PASS", (
        f"{case_dir.name}: expected_catcher {result['expected_catcher']!r} "
        f"regressed (status={result['status']}); summary={result['summary']!r}, "
        f"findings={result['findings']!r}"
    )
