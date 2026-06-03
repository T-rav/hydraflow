"""Unit tests for the adversarial corpus runner's per-case evaluation.

Tests behaviour against synthetic case directories — proves the runner
synthesizes diffs, enforces the keyword assertion, accepts the `none`
sentinel, and rejects unknown catcher names. Does NOT run the real corpus
(that's the RC gate's job). Complements test_adversarial_corpus_runner.py,
which covers the loop-facing JSON schema against the committed corpus.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ADV = Path(__file__).resolve().parent / "trust" / "adversarial"
if str(_ADV) not in sys.path:
    sys.path.insert(0, str(_ADV))

from corpus_runner import (  # noqa: E402
    evaluate_case,
    read_expected_catcher,
    read_keyword,
    synthesize_diff,
)


def _write_case(
    tmp_cases: Path,
    name: str,
    *,
    before: dict[str, str],
    after: dict[str, str],
    catcher: str,
    keyword: str = "scope",
    plan: str | None = None,
    transcript: str | None = None,
) -> Path:
    case = tmp_cases / name
    (case / "before").mkdir(parents=True)
    (case / "after").mkdir()
    for rel, text in before.items():
        target = case / "before" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    for rel, text in after.items():
        target = case / "after" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    (case / "expected_catcher.txt").write_text(catcher)
    (case / "README.md").write_text(f"# {name}\n\nKeyword: {keyword}\n")
    if plan is not None:
        (case / "plan.md").write_text(plan)
    if transcript is not None:
        (case / "expected_transcript.txt").write_text(transcript)
    return case


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


def test_synthesize_diff_produces_git_headers(tmp_path: Path) -> None:
    (tmp_path / "before").mkdir()
    (tmp_path / "after").mkdir()
    (tmp_path / "before" / "x.py").write_text("old\n")
    (tmp_path / "after" / "x.py").write_text("new\n")
    diff = synthesize_diff(tmp_path / "before", tmp_path / "after")
    assert "diff --git a/x.py b/x.py" in diff
    assert "-old" in diff and "+new" in diff


def test_read_keyword_extracts_line(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# title\n\nKeyword: scope creep\n\nmore\n")
    assert read_keyword(tmp_path / "README.md") == "scope creep"


def test_read_keyword_missing_raises(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# title\n\nno keyword line\n")
    with pytest.raises(AssertionError, match="missing 'Keyword:' line"):
        read_keyword(tmp_path / "README.md")


def test_read_expected_catcher_rejects_unknown(tmp_path: Path) -> None:
    (tmp_path / "expected_catcher.txt").write_text("bogus-skill\n")
    with pytest.raises(AssertionError, match="must be one of"):
        read_expected_catcher(tmp_path)


def test_read_expected_catcher_accepts_sentinel(tmp_path: Path) -> None:
    (tmp_path / "expected_catcher.txt").write_text("none\n")
    assert read_expected_catcher(tmp_path) == "none"


def test_read_expected_catcher_accepts_registered_skills(tmp_path: Path) -> None:
    # Pull a real skill name from the live registry so the test tracks changes.
    from skill_registry import BUILTIN_SKILLS  # noqa: PLC0415

    name = BUILTIN_SKILLS[0].name
    (tmp_path / "expected_catcher.txt").write_text(name + "\n")
    assert read_expected_catcher(tmp_path) == name


# ---------------------------------------------------------------------------
# evaluate_case behaviour (synthetic cases + canned transcripts)
# ---------------------------------------------------------------------------


def test_catcher_flags_with_keyword_is_pass(tmp_path: Path) -> None:
    """A transcript where the expected catcher flags + the keyword matches -> PASS."""
    case = _write_case(
        tmp_path / "cases",
        "scope-creep-synthetic",
        before={"src/foo.py": "x = 1\n"},
        after={"src/foo.py": "x = 1\n", "src/unrelated.py": "y = 2\n"},
        catcher="scope-check",
        keyword="scope",
        plan="## Plan\n- Edit `src/foo.py`\n",
        transcript=(
            "SCOPE_CHECK_RESULT: RETRY\n"
            "SUMMARY: unplanned file src/unrelated.py is scope creep\n"
            "FINDINGS:\n- src/unrelated.py — not in plan\n"
        ),
    )
    assert evaluate_case(case, strict=False)["status"] == "PASS"


def test_catcher_flags_without_keyword_is_fail(tmp_path: Path) -> None:
    """Flagged but the required keyword is absent -> the catch regressed -> FAIL."""
    case = _write_case(
        tmp_path / "cases",
        "scope-creep-no-keyword",
        before={"src/foo.py": "x = 1\n"},
        after={"src/foo.py": "x = 1\n", "src/unrelated.py": "y = 2\n"},
        catcher="scope-check",
        keyword="scope",
        plan="## Plan\n- Edit `src/foo.py`\n",
        transcript=(
            "SCOPE_CHECK_RESULT: RETRY\n"
            "SUMMARY: something vague\n"
            "FINDINGS:\n- src/unrelated.py — not in plan\n"
        ),
    )
    assert evaluate_case(case, strict=False)["status"] == "FAIL"


def test_catcher_returns_ok_is_fail(tmp_path: Path) -> None:
    """The expected catcher passed the case through (no flag) -> FAIL."""
    case = _write_case(
        tmp_path / "cases",
        "scope-creep-ok-returned",
        before={"src/foo.py": "x = 1\n"},
        after={"src/foo.py": "x = 1\n", "src/unrelated.py": "y = 2\n"},
        catcher="scope-check",
        keyword="scope",
        plan="## Plan\n- Edit `src/foo.py`\n",
        transcript="SCOPE_CHECK_RESULT: OK\nSUMMARY: nothing unusual\n",
    )
    assert evaluate_case(case, strict=False)["status"] == "FAIL"


def test_sentinel_none_passes_when_all_skills_ok(tmp_path: Path) -> None:
    """A benign 'none' case no skill flags -> PASS."""
    case = _write_case(
        tmp_path / "cases",
        "benign-noop",
        before={"src/foo.py": "x = 1\n"},
        after={"src/foo.py": "x = 2\n"},
        catcher="none",
        keyword="ignored",
        transcript="No issues found.\n",
    )
    assert evaluate_case(case, strict=False)["status"] == "PASS"
