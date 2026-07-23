"""Unit tests for the pure change-spread sensor (files-touched + modules-crossed)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from arch._models import ModuleGraph, ModuleNode
from erosion.baseline import SpreadBaseline, is_flagged
from erosion.spread import changed_files_for_range, compute


def _graph(*names: str) -> ModuleGraph:
    return ModuleGraph(nodes=[ModuleNode(name=n) for n in names])


def test_low_spread_change_stays_within_one_module_and_is_not_flagged() -> None:
    graph = _graph("src.disturbance", "src.disturbance.detectors", "src.erosion")
    finding = compute(
        [
            "src/disturbance/detectors/base.py",
            "src/disturbance/detectors/traceability.py",
            "src/disturbance/registry.py",
        ],
        graph,
    )

    assert finding.files_touched == 3
    assert finding.modules_crossed == 2
    assert finding.modules == ("src.disturbance", "src.disturbance.detectors")
    assert finding.unmapped_files == ()
    assert not is_flagged(finding, SpreadBaseline(max_spread_ratio=1.0))


def test_high_spread_change_crosses_many_modules_for_its_size_and_is_flagged() -> None:
    graph = _graph("src.a", "src.b", "src.c", "src.d", "src.e")
    finding = compute(
        ["src/a/x.py", "src/b/y.py", "src/c/z.py", "src/d/w.py", "src/e/v.py"],
        graph,
    )

    assert finding.files_touched == 5
    assert finding.modules_crossed == 5
    assert finding.spread_ratio == 1.0
    assert is_flagged(finding, SpreadBaseline(max_spread_ratio=0.5))
    assert not is_flagged(finding, SpreadBaseline(max_spread_ratio=1.0))


def test_unmapped_files_are_tracked_not_dropped_and_excluded_from_modules_crossed() -> (
    None
):
    graph = _graph("src.disturbance")
    finding = compute(
        [
            "src/disturbance/baseline.py",
            "docs/wiki/gotchas.md",  # outside src/ entirely
            "src/ghost_dir/vanished.py",  # under src/ but not a known module node
        ],
        graph,
    )

    assert finding.files_touched == 3
    assert finding.modules_crossed == 1
    assert finding.modules == ("src.disturbance",)
    assert finding.unmapped_files == (
        "docs/wiki/gotchas.md",
        "src/ghost_dir/vanished.py",
    )


def test_no_changed_files_is_zero_and_never_flagged() -> None:
    finding = compute([], _graph("src.a"))

    assert finding.files_touched == 0
    assert finding.modules_crossed == 0
    assert finding.spread_ratio == 0.0
    assert not is_flagged(finding, SpreadBaseline(max_spread_ratio=0.0))


def test_duplicate_changed_files_are_deduplicated() -> None:
    finding = compute(["src/a/x.py", "src/a/x.py"], _graph("src.a"))

    assert finding.files_touched == 1
    assert finding.modules_crossed == 1


def test_top_level_src_file_maps_to_the_src_package() -> None:
    finding = compute(["src/config.py"], _graph("src"))

    assert finding.modules == ("src",)
    assert finding.unmapped_files == ()


def test_changed_files_for_range_wraps_git_diff_name_only(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("one\n")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("two\n")
    (tmp_path / "b.txt").write_text("new\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "change"], cwd=tmp_path, check=True)

    files = changed_files_for_range(tmp_path, "HEAD~1..HEAD")

    assert files == ["a.txt", "b.txt"]


def test_changed_files_for_range_returns_none_on_bad_range(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    assert changed_files_for_range(tmp_path, "not-a-real..range") is None


def test_changed_files_for_range_returns_none_outside_a_repo(tmp_path: Path) -> None:
    assert changed_files_for_range(tmp_path, "HEAD~1..HEAD") is None
