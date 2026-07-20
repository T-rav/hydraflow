"""Regression: make quality must run lint serially before the parallel block."""

from pathlib import Path

MAKEFILE = Path(__file__).parent.parent / "Makefile"


def test_lint_runs_before_parallel_block() -> None:
    text = MAKEFILE.read_text()
    quality_start = text.index("quality: deps lint-ul")
    quality_end = text.index("\nquality-lite:", quality_start)
    recipe = text[quality_start:quality_end]

    # Lint preamble must appear before the parallel-job block opener
    lint_pos = recipe.index("ruff check .")
    parallel_pos = recipe.index("& \\")
    assert lint_pos < parallel_pos, (
        "make quality: lint must execute serially before the & parallel block"
    )

    # Lint line must NOT end with ' &' (i.e., it is not a background job)
    lint_line = next(ln for ln in recipe.splitlines() if "ruff check ." in ln)
    assert not lint_line.rstrip().endswith("&"), (
        "make quality: lint preamble line must not be a background job"
    )


def _quality_recipe() -> str:
    text = MAKEFILE.read_text()
    quality_start = text.index("quality: deps lint-ul")
    quality_end = text.index("\nquality-lite:", quality_start)
    return text[quality_start:quality_end]


def test_ui_vitest_stage_is_parallel_job_in_quality() -> None:
    """#9875: quality must run the UI vitest stage inside the parallel block."""
    recipe = _quality_recipe()

    ui_line = next((ln for ln in recipe.splitlines() if "UI_TEST_CMD" in ln), None)
    assert ui_line is not None, (
        "make quality: the UI vitest stage ($(UI_TEST_CMD)) is missing — "
        "src/ui changes would pass local quality while CI Dashboard Build "
        "goes red (issue #9875)"
    )

    # Background job (parallelised alongside pyright/bandit/pytest), placed
    # before the wait loop so its exit code is collected by wait_result.
    assert ui_line.rstrip().endswith("& \\"), (
        "make quality: the UI vitest stage must be a background job "
        "('& \\') inside the parallel block"
    )
    assert recipe.index("UI_TEST_CMD") < recipe.index("wait_result=0"), (
        "make quality: the UI vitest stage must start before the wait loop "
        "so its exit code propagates into wait_result"
    )


def test_ui_vitest_stage_not_in_quality_lite() -> None:
    """#9875: quality-lite is the pre-push gate — it must stay vitest-free."""
    text = MAKEFILE.read_text()
    lite_start = text.index("\nquality-lite:")
    lite_end = text.index("\ninstall:", lite_start)
    recipe = text[lite_start:lite_end]

    assert "UI_TEST_CMD" not in recipe and "vitest" not in recipe, (
        "quality-lite must not run the UI vitest suite: pre-push stays fast "
        "by design (see the comment above quality-lite; issue #9875)"
    )
