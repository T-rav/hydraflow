"""prompt_refiner context assembly, holdout invariant, patch parsing."""

from pathlib import Path

import pytest

from prompt_refiner import (
    PatchParseError,
    assemble_refine_context,
    parse_patch_response,
)
from tests.trust.adversarial.corpus_runner import CASES_DIR, discover_cases, is_holdout


def test_context_contains_builder_source_and_case_material(tmp_path: Path) -> None:
    case = tmp_path / "some-case"
    (case / "before").mkdir(parents=True)
    (case / "after").mkdir()
    (case / "README.md").write_text("# some-case\nKeyword: kw-1\n")
    (case / "expected_transcript.txt").write_text("EXPECTED-MARKER\n")
    ctx = assemble_refine_context(
        Path.cwd(), case, "diff-sanity", failure_transcript="FAILED-MARKER"
    )
    assert "build_diff_sanity_prompt" in ctx  # builder source embedded
    assert "kw-1" in ctx and "EXPECTED-MARKER" in ctx and "FAILED-MARKER" in ctx


def test_context_refuses_holdout_case(tmp_path: Path) -> None:
    case = tmp_path / "trap"
    (case / "before").mkdir(parents=True)
    (case / "after").mkdir()
    (case / "HOLDOUT").write_text("")
    with pytest.raises(ValueError, match="holdout"):
        assemble_refine_context(Path.cwd(), case, "diff-sanity", failure_transcript="")


def test_no_holdout_content_reachable_via_context() -> None:
    """The structural invariant: for every real non-holdout case, the assembled
    context never contains any holdout case's id or README keyword."""
    holdouts = [c for c in discover_cases(CASES_DIR) if is_holdout(c)]
    assert holdouts, "seed holdout cases missing"
    normal = list(discover_cases(CASES_DIR, include_holdout=False))[:3]
    for case in normal:
        ctx = assemble_refine_context(
            Path.cwd(), case, "diff-sanity", failure_transcript="x"
        )
        for trap in holdouts:
            assert trap.name not in ctx


def test_parse_patch_response_extracts_diff_fence() -> None:
    text = "reasoning...\n```diff\n--- a/src/diff_sanity.py\n+++ b/src/diff_sanity.py\n@@ -1 +1 @@\n-a\n+b\n```\ndone"
    assert parse_patch_response(text).startswith("--- a/src/diff_sanity.py")


def test_parse_patch_response_rejects_missing_fence() -> None:
    with pytest.raises(PatchParseError):
        parse_patch_response("no diff here")
