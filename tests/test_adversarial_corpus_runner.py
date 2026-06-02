"""Unit tests for the adversarial corpus runner (the FORMAT=json producer).

Guards the contract SkillPromptEvalLoop._run_corpus depends on: a JSON list of
{case_id, skill, status, provenance, expected_catcher} dicts.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ADV = Path(__file__).resolve().parent / "trust" / "adversarial"
if str(_ADV) not in sys.path:
    sys.path.insert(0, str(_ADV))

from corpus_runner import (  # noqa: E402
    CASES_DIR,
    MissingTranscriptError,
    evaluate_case,
    run_corpus,
)

_LOOP_KEYS = {"case_id", "skill", "status", "provenance", "expected_catcher"}
_VALID_STATUS = {"PASS", "FAIL", "SKIPPED"}


def test_run_corpus_returns_loop_schema() -> None:
    """Every result carries exactly the keys the loop reads, with a valid status."""
    results = run_corpus(strict=False)
    assert results, "expected a non-empty committed adversarial corpus"
    for r in results:
        assert set(r) >= _LOOP_KEYS, f"missing loop keys: {_LOOP_KEYS - set(r)}"
        assert r["status"] in _VALID_STATUS
        assert r["case_id"]


def test_committed_corpus_is_all_green() -> None:
    """The committed fixtures must currently PASS (this is the loop's last-green
    baseline); a FAIL here means a skill prompt regressed."""
    failing = [r["case_id"] for r in run_corpus(strict=False) if r["status"] == "FAIL"]
    assert not failing, f"corpus cases regressed to FAIL: {failing}"


def test_evaluate_real_catcher_case() -> None:
    case = CASES_DIR / "missing-import"
    if not case.is_dir():
        pytest.skip("missing-import case not present")
    result = evaluate_case(case, strict=False)
    assert result["expected_catcher"] == "diff-sanity"
    assert result["skill"] == "diff-sanity"
    assert result["status"] == "PASS"


def test_evaluate_real_sentinel_case() -> None:
    case = CASES_DIR / "benign-rename-sentinel"
    if not case.is_dir():
        pytest.skip("benign-rename-sentinel case not present")
    result = evaluate_case(case, strict=False)
    assert result["expected_catcher"] == "none"
    assert result["status"] == "PASS"


def _make_case_without_transcript(tmp_path: Path) -> Path:
    case = tmp_path / "synthetic-case"
    (case / "before").mkdir(parents=True)
    (case / "after").mkdir(parents=True)
    (case / "before" / "x.py").write_text("a = 1\n")
    (case / "after" / "x.py").write_text("a = 2\n")
    (case / "expected_catcher.txt").write_text("diff-sanity\n")
    (case / "README.md").write_text("Keyword: something\n")
    return case


def test_missing_transcript_skipped_when_not_strict(tmp_path: Path) -> None:
    case = _make_case_without_transcript(tmp_path)
    result = evaluate_case(case, live=False, strict=False)
    assert result["status"] == "SKIPPED"


def test_missing_transcript_raises_when_strict(tmp_path: Path) -> None:
    case = _make_case_without_transcript(tmp_path)
    with pytest.raises(MissingTranscriptError):
        evaluate_case(case, live=False, strict=True)
