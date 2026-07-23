"""Unit tests for the pure concept-scatter sensor (newly-added symbol across K modules)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from arch._models import ModuleGraph, ModuleNode
from erosion.scatter import (
    DEFAULT_SCATTER_THRESHOLD,
    added_symbols_for_range,
    compute,
)


def _graph(*names: str) -> ModuleGraph:
    return ModuleGraph(nodes=[ModuleNode(name=n) for n in names])


def test_symbol_added_to_only_two_modules_is_not_flagged() -> None:
    graph = _graph("src.a", "src.b")
    finding = compute(
        {
            "src/a/x.py": ["do_thing"],
            "src/b/y.py": ["do_thing"],
        },
        graph,
    )

    assert finding.scattered == ()
    assert not finding.is_flagged
    assert finding.threshold == DEFAULT_SCATTER_THRESHOLD


def test_symbol_added_to_three_distinct_modules_is_flagged() -> None:
    graph = _graph("src.a", "src.b", "src.c")
    finding = compute(
        {
            "src/a/x.py": ["do_thing"],
            "src/b/y.py": ["do_thing"],
            "src/c/z.py": ["do_thing"],
        },
        graph,
    )

    assert finding.is_flagged
    assert len(finding.scattered) == 1
    scattered = finding.scattered[0]
    assert scattered.symbol == "do_thing"
    assert scattered.modules == ("src.a", "src.b", "src.c")
    assert scattered.files == ("src/a/x.py", "src/b/y.py", "src/c/z.py")


def test_symbol_added_to_many_files_within_the_same_module_is_not_flagged() -> None:
    # Same module reached via three DIFFERENT files: K counts distinct
    # modules, not files (#10106's definition is explicit about this).
    graph = _graph("src.a")
    finding = compute(
        {
            "src/a/x.py": ["do_thing"],
            "src/a/y.py": ["do_thing"],
            "src/a/z.py": ["do_thing"],
        },
        graph,
    )

    assert finding.scattered == ()


def test_custom_threshold_overrides_default() -> None:
    graph = _graph("src.a", "src.b")
    finding = compute(
        {"src/a/x.py": ["helper"], "src/b/y.py": ["helper"]},
        graph,
        threshold=2,
    )

    assert finding.threshold == 2
    assert len(finding.scattered) == 1
    assert finding.scattered[0].symbol == "helper"


def test_unmapped_files_are_tracked_and_excluded_from_the_module_tally() -> None:
    graph = _graph("src.a", "src.b")
    finding = compute(
        {
            "src/a/x.py": ["helper"],
            "src/b/y.py": ["helper"],
            "docs/wiki/gotchas.md": ["helper"],  # outside src/ entirely
            "src/ghost_dir/vanished.py": ["helper"],  # under src/, unknown module
        },
        graph,
        threshold=2,
    )

    assert finding.unmapped_files == (
        "docs/wiki/gotchas.md",
        "src/ghost_dir/vanished.py",
    )
    # unmapped files still don't push a symbol over the module threshold
    # on their own, but they don't block the OTHER mapped files from
    # meeting it either.
    assert len(finding.scattered) == 1
    assert finding.scattered[0].modules == ("src.a", "src.b")
    assert finding.scattered[0].files == (
        "docs/wiki/gotchas.md",
        "src/a/x.py",
        "src/b/y.py",
        "src/ghost_dir/vanished.py",
    )


def test_multiple_distinct_symbols_are_evaluated_independently() -> None:
    graph = _graph("src.a", "src.b", "src.c")
    finding = compute(
        {
            "src/a/x.py": ["scattered_one", "solo"],
            "src/b/y.py": ["scattered_one"],
            "src/c/z.py": ["scattered_one"],
        },
        graph,
    )

    symbols = {s.symbol for s in finding.scattered}
    assert symbols == {"scattered_one"}


def test_no_added_symbols_yields_no_scatter() -> None:
    finding = compute({}, _graph("src.a"))

    assert finding.scattered == ()
    assert not finding.is_flagged
    assert finding.unmapped_files == ()


def test_files_with_no_added_symbols_are_ignored() -> None:
    finding = compute({"src/a/x.py": []}, _graph("src.a"))

    assert finding.scattered == ()
    assert finding.unmapped_files == ()


def test_scattered_symbols_are_sorted_by_name() -> None:
    graph = _graph("src.a", "src.b", "src.c")
    finding = compute(
        {
            "src/a/x.py": ["zeta", "alpha"],
            "src/b/y.py": ["zeta", "alpha"],
            "src/c/z.py": ["zeta", "alpha"],
        },
        graph,
    )

    assert [s.symbol for s in finding.scattered] == ["alpha", "zeta"]


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)


def test_added_symbols_for_range_extracts_new_def_class_and_constant_names(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)

    (tmp_path / "a.py").write_text(
        "VALUE = 1\n\n\ndef do_thing():\n    pass\n\n\nclass Widget:\n    pass\n\n\nMAX = 5\n"
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "change"], cwd=tmp_path, check=True)

    added = added_symbols_for_range(tmp_path, "HEAD~1..HEAD")

    assert added is not None
    assert set(added["a.py"]) == {"do_thing", "Widget", "MAX"}


def test_added_symbols_for_range_ignores_dunder_names(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("class Widget:\n    pass\n")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)

    (tmp_path / "a.py").write_text(
        "class Widget:\n    def __init__(self):\n        pass\n"
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "change"], cwd=tmp_path, check=True)

    added = added_symbols_for_range(tmp_path, "HEAD~1..HEAD")

    assert added is not None
    assert added.get("a.py", []) == []


def test_added_symbols_for_range_ignores_non_python_files(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.md").write_text("# doc\n")
    subprocess.run(["git", "add", "a.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)

    (tmp_path / "a.md").write_text("# doc\n\ndef not_python():\n    pass\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "change"], cwd=tmp_path, check=True)

    added = added_symbols_for_range(tmp_path, "HEAD~1..HEAD")

    assert added == {}


def test_added_symbols_for_range_returns_none_on_bad_range(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    assert added_symbols_for_range(tmp_path, "not-a-real..range") is None


def test_added_symbols_for_range_returns_none_outside_a_repo(tmp_path: Path) -> None:
    assert added_symbols_for_range(tmp_path, "HEAD~1..HEAD") is None
