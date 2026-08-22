"""Regression: make quality must run lint serially before the parallel block."""

import re
from pathlib import Path

MAKEFILE = Path(__file__).parent.parent / "Makefile"


def _make_assignment_tokens(name: str) -> set[str]:
    text = MAKEFILE.read_text()
    match = re.search(
        rf"^{re.escape(name)}[ \t]*(?::=|\?=|=)[ \t]*(.*?)(?<!\\)\n",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"no `{name}` assignment found in Makefile"
    return set(match.group(1).replace("\\", " ").split())


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


def test_host_exclusive_tests_run_foreground_before_parallel_block() -> None:
    """#11219/#11434: host-global tests cannot overlap any quality job."""
    recipe = _quality_recipe()
    host_line = next(
        ln
        for ln in recipe.splitlines()
        if "pytest $(PYTEST_HOST_EXCLUSIVE_PATHS)" in ln
    )

    assert recipe.index(host_line) < recipe.index("& \\"), (
        "host-exclusive tests must finish before quality starts background jobs"
    )
    assert not host_line.rstrip().endswith("& \\"), (
        "host-exclusive tests must run in the foreground"
    )

    host_paths = _make_assignment_tokens("PYTEST_HOST_EXCLUSIVE_PATHS")
    assert host_paths == {
        "tests/test_quality_host_lock.py",
        "tests/regressions/test_issue_11434.py",
    }

    serial_paths = _make_assignment_tokens("PYTEST_SERIAL_PATHS")
    serial_paths.remove("$(REAP_TESTS)")
    serial_paths.update(_make_assignment_tokens("REAP_TESTS"))
    assert host_paths <= serial_paths, (
        "host-exclusive paths must remain in PYTEST_SERIAL_IGNORE so the "
        "parallel bulk cannot collect them"
    )
    assert (
        "PYTEST_SERIAL_IGNORE := $(addprefix --ignore=,$(PYTEST_SERIAL_PATHS))"
        in MAKEFILE.read_text()
    )


def test_background_serial_leg_excludes_host_exclusive_tests() -> None:
    """The foreground suites must not be duplicated by the background leg."""
    text = MAKEFILE.read_text()
    assert (
        "PYTEST_QUALITY_BACKGROUND_SERIAL_PATHS := "
        "$(filter-out $(PYTEST_HOST_EXCLUSIVE_PATHS),$(PYTEST_SERIAL_PATHS))" in text
    )

    serial_line = next(
        ln for ln in _quality_recipe().splitlines() if "[serial-tests OK]" in ln
    )
    assert "$(PYTEST_QUALITY_BACKGROUND_SERIAL_PATHS)" in serial_line
    assert "pytest $(PYTEST_SERIAL_PATHS)" not in serial_line


def test_gateway_package_branch_coverage_gate_is_contractual() -> None:
    """#11470: package coverage cannot silently fall back to the repo floor."""
    text = MAKEFILE.read_text()
    target_start = text.index("\ngateway-coverage:")
    target_end = text.index("\n\n", target_start)
    target_recipe = text[target_start:target_end]

    assert _make_assignment_tokens("GATEWAY_PACKAGE_TEST_PATHS") == {
        "tests/test_gateway_*.py",
        "tests/test_routing_*.py",
    }
    assert _make_assignment_tokens("GATEWAY_PACKAGE_COVERAGE_MIN") == {"85"}
    command = _make_assignment_tokens("GATEWAY_PACKAGE_COVERAGE_CMD")
    assert "--cov=hydraflow_gateway" in command
    assert "--cov-branch" in command
    assert "--cov-fail-under=$(GATEWAY_PACKAGE_COVERAGE_MIN)" in command
    assert "$(GATEWAY_PACKAGE_COVERAGE_CMD)" in target_recipe

    quality_recipe = _quality_recipe()
    coverage_line = next(
        ln for ln in quality_recipe.splitlines() if "[gateway-coverage OK]" in ln
    )
    assert "$(GATEWAY_PACKAGE_COVERAGE_CMD)" in coverage_line
    assert quality_recipe.index(coverage_line) < quality_recipe.index("& \\"), (
        "the focused coverage gate must fail fast before quality background jobs"
    )
    assert not coverage_line.rstrip().endswith("& \\"), (
        "the focused coverage gate must not contend with the parallel test lane"
    )
    bulk_test_line = next(
        ln for ln in quality_recipe.splitlines() if 'echo "[tests OK]"' in ln
    )
    assert "$(GATEWAY_PACKAGE_TEST_IGNORES)" in bulk_test_line, (
        "quality must not run the focused gateway files twice"
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
