"""Unit tests for the impacted-test selection mapping (scripts/impacted_tests.py).

Each mapping rule is exercised in isolation against an in-memory fake file tree
so the tests are hermetic and fast — no real filesystem, no git. The one test
that touches the real repo asserts the SMOKE constants and architecture glob
have not drifted out from under the tool.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# scripts/ is not an importable package from the tests root, so load the module
# by path. (Repo convention: scripts are executable modules, not a package.)
# It must be registered in sys.modules before exec so that dataclasses defined
# under ``from __future__ import annotations`` can resolve the module namespace.
_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "impacted_tests.py"
_spec = importlib.util.spec_from_file_location("impacted_tests", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
impacted_tests = importlib.util.module_from_spec(_spec)
sys.modules["impacted_tests"] = impacted_tests
_spec.loader.exec_module(impacted_tests)

FULL_SUITE_SENTINEL = impacted_tests.FULL_SUITE_SENTINEL
InMemoryFileIndex = impacted_tests.InMemoryFileIndex
RealFileIndex = impacted_tests.RealFileIndex
Selection = impacted_tests.Selection
classify_path = impacted_tests.classify_path
select_tests = impacted_tests.select_tests
# NB: do not alias ``tests_for_module_stem`` at module scope — a name starting
# with "test" would be collected by pytest as a test. Reference it via the
# module object instead.
map_stem = impacted_tests.tests_for_module_stem

# A minimal fake tree that includes the always-on floor (architecture + smoke)
# plus a few representative source/test files.
_FAKE_TREE = frozenset(
    {
        # architecture guards (rule c)
        "tests/architecture/test_guard_one.py",
        "tests/architecture/test_guard_two.py",
        "tests/architecture/conftest.py",  # not a test module; not globbed
        # smoke (rule d) — all declared smoke files present
        *impacted_tests.SMOKE_TESTS,
        # a mappable src module with matching tests (rule b)
        "src/widget.py",
        "tests/test_widget.py",
        "tests/test_widget_edge.py",
        "tests/test_widgetry.py",  # matched by the test_<mod>*.py superset glob
        "tests/regressions/regression_issue_4242_widget.py",
        # an unrelated src module + its test (must NOT be pulled in by widget)
        "src/gadget.py",
        "tests/test_gadget.py",
        # a src module with NO name-matching test (rule b conservative fallback)
        "src/orphan_module.py",
        # shared test infra (rule a -> full suite)
        "tests/helpers.py",
        # scripts self-mapping
        "scripts/impacted_tests.py",
        "tests/test_impacted_tests.py",
    }
)


@pytest.fixture
def fs() -> InMemoryFileIndex:
    return InMemoryFileIndex(_FAKE_TREE)


# ── rule (a): direct test change ────────────────────────────────────────────


def test_changed_test_module_is_included_directly(fs: InMemoryFileIndex) -> None:
    tests, reason = classify_path("tests/test_gadget.py", fs)
    assert reason is None
    assert tests == frozenset({"tests/test_gadget.py"})


def test_changed_regression_module_is_included_directly(
    fs: InMemoryFileIndex,
) -> None:
    tests, reason = classify_path(
        "tests/regressions/regression_issue_4242_widget.py", fs
    )
    assert reason is None
    assert tests == frozenset({"tests/regressions/regression_issue_4242_widget.py"})


def test_changed_shared_test_infra_triggers_full_suite(
    fs: InMemoryFileIndex,
) -> None:
    tests, reason = classify_path("tests/helpers.py", fs)
    assert tests == frozenset()
    assert reason is not None and "full suite" in reason


def test_changed_test_package_init_maps_to_nothing(fs: InMemoryFileIndex) -> None:
    tests, reason = classify_path("tests/__init__.py", fs)
    assert tests == frozenset()
    assert reason is None


# ── rule (b): src -> test mapping ───────────────────────────────────────────


def test_src_change_maps_to_matching_existing_tests(fs: InMemoryFileIndex) -> None:
    tests, reason = classify_path("src/widget.py", fs)
    assert reason is None
    assert tests == frozenset(
        {
            "tests/test_widget.py",
            "tests/test_widget_edge.py",
            "tests/test_widgetry.py",
            "tests/regressions/regression_issue_4242_widget.py",
        }
    )


def test_src_mapping_does_not_pull_unrelated_module_tests(
    fs: InMemoryFileIndex,
) -> None:
    tests, _ = classify_path("src/widget.py", fs)
    assert "tests/test_gadget.py" not in tests


def test_stem_mapping_only_returns_existing_files(
    fs: InMemoryFileIndex,
) -> None:
    # ``gadget`` exists as test_gadget.py; a bogus stem yields nothing.
    assert map_stem("gadget", fs) == frozenset({"tests/test_gadget.py"})
    assert map_stem("does_not_exist_anywhere", fs) == frozenset()


def test_unmapped_src_triggers_full_suite(fs: InMemoryFileIndex) -> None:
    tests, reason = classify_path("src/orphan_module.py", fs)
    assert tests == frozenset()
    assert reason is not None and "full suite" in reason


def test_non_python_src_asset_maps_to_nothing(fs: InMemoryFileIndex) -> None:
    tests, reason = classify_path("src/assets/logo.svg", fs)
    assert tests == frozenset()
    assert reason is None


# ── rule (e): high-fanout fallback -> sentinel ──────────────────────────────


@pytest.mark.parametrize("hot", sorted(impacted_tests.HIGH_FANOUT_SRC))
def test_high_fanout_src_forces_full_suite(hot: str, fs: InMemoryFileIndex) -> None:
    tests, reason = classify_path(hot, fs)
    assert tests == frozenset()
    assert reason is not None and "full suite" in reason


def test_src_arch_change_forces_full_suite(fs: InMemoryFileIndex) -> None:
    _, reason = classify_path("src/arch/extractors/loops.py", fs)
    assert reason is not None and "full suite" in reason


@pytest.mark.parametrize(
    "cfg",
    ["conftest.py", "tests/conftest.py", "pyproject.toml", "pytest.ini"],
)
def test_config_files_force_full_suite(cfg: str, fs: InMemoryFileIndex) -> None:
    _, reason = classify_path(cfg, fs)
    assert reason is not None and "full suite" in reason


def test_select_returns_sentinel_selection_on_high_fanout(
    fs: InMemoryFileIndex,
) -> None:
    result = select_tests(["src/widget.py", "src/config.py"], fs)
    assert result.full_suite is True
    assert result.test_files == ()
    assert any("config.py" in r for r in result.reasons)


# ── rule (f): workflow / Makefile / hooks -> sentinel; docs -> empty ────────


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        "Makefile",
        ".githooks/pre-push",
    ],
)
def test_infra_change_forces_full_suite(path: str, fs: InMemoryFileIndex) -> None:
    _, reason = classify_path(path, fs)
    assert reason is not None and "full suite" in reason


@pytest.mark.parametrize(
    "path",
    [
        "docs/wiki/index.md",
        "README.md",
        ".github/ISSUE_TEMPLATE/bug.md",
        "src/ui/App.jsx",
    ],
)
def test_docs_and_non_mapped_files_map_to_nothing(
    path: str, fs: InMemoryFileIndex
) -> None:
    tests, reason = classify_path(path, fs)
    assert tests == frozenset()
    assert reason is None


def test_docs_only_diff_selects_only_the_always_floor(
    fs: InMemoryFileIndex,
) -> None:
    result = select_tests(["docs/wiki/index.md", "README.md"], fs)
    assert result.full_suite is False
    # Exactly the architecture guards + smoke, nothing mapped.
    expected = {
        "tests/architecture/test_guard_one.py",
        "tests/architecture/test_guard_two.py",
        *impacted_tests.SMOKE_TESTS,
    }
    assert set(result.test_files) == expected


# ── scripts self-mapping ────────────────────────────────────────────────────


def test_scripts_change_maps_to_its_test_not_full_suite(
    fs: InMemoryFileIndex,
) -> None:
    tests, reason = classify_path("scripts/impacted_tests.py", fs)
    assert reason is None
    assert tests == frozenset({"tests/test_impacted_tests.py"})


def test_unmapped_script_maps_to_nothing_not_full_suite(
    fs: InMemoryFileIndex,
) -> None:
    tests, reason = classify_path("scripts/some_tool_without_test.py", fs)
    assert tests == frozenset()
    assert reason is None


# ── rules (c)+(d): always-on floor + full end-to-end selection ──────────────


def test_architecture_and_smoke_always_included_for_src_change(
    fs: InMemoryFileIndex,
) -> None:
    result = select_tests(["src/widget.py"], fs)
    assert result.full_suite is False
    selected = set(result.test_files)
    # rule (c): architecture guards present (globbed test modules only)
    assert "tests/architecture/test_guard_one.py" in selected
    assert "tests/architecture/test_guard_two.py" in selected
    assert "tests/architecture/conftest.py" not in selected
    # rule (d): every smoke test present
    assert set(impacted_tests.SMOKE_TESTS).issubset(selected)
    # rule (b): the widget tests present
    assert "tests/test_widget.py" in selected


def test_selection_is_sorted_and_deduped(fs: InMemoryFileIndex) -> None:
    # Pass the same test twice + a mapped src; result must be sorted & unique.
    result = select_tests(
        ["tests/test_widget.py", "tests/test_widget.py", "src/widget.py"], fs
    )
    assert list(result.test_files) == sorted(set(result.test_files))


def test_empty_diff_still_runs_the_floor(fs: InMemoryFileIndex) -> None:
    result = select_tests([], fs)
    assert result.full_suite is False
    assert "tests/architecture/test_guard_one.py" in result.test_files
    assert set(impacted_tests.SMOKE_TESTS).issubset(set(result.test_files))


def test_blank_paths_are_ignored(fs: InMemoryFileIndex) -> None:
    tests, reason = classify_path("   ", fs)
    assert tests == frozenset()
    assert reason is None


# ── in-memory glob parity guard ─────────────────────────────────────────────


def test_inmemory_glob_does_not_cross_directories() -> None:
    index = InMemoryFileIndex(
        frozenset({"tests/test_a.py", "tests/sub/test_a_deep.py"})
    )
    # ``tests/test_a*.py`` must not reach into tests/sub/ (Path.glob semantics).
    assert index.glob("tests/test_a*.py") == ["tests/test_a.py"]


# ── real-repo drift guard (only real-FS test) ───────────────────────────────


def test_smoke_and_architecture_constants_exist_in_repo() -> None:
    """Guard: the declared SMOKE files and architecture glob must still exist.

    If a smoke file is renamed/removed, this fails loudly rather than the tool
    silently dropping a core guard.
    """
    root = Path(__file__).resolve().parents[1]
    fs = RealFileIndex(root)
    missing = [f for f in impacted_tests.SMOKE_TESTS if not fs.exists(f)]
    assert not missing, f"SMOKE_TESTS drifted (missing): {missing}"
    arch = [m for g in impacted_tests.ARCHITECTURE_GLOBS for m in fs.glob(g)]
    assert arch, "no tests/architecture/test_*.py found — floor would be empty"
