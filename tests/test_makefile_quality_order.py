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
