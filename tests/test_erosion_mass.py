"""Unit tests for the mass (god-file / god-class size) sensor."""

from __future__ import annotations

from pathlib import Path

from erosion.mass import (
    DEFAULT_CLASS_LOC_THRESHOLD,
    DEFAULT_CLASS_METHOD_THRESHOLD,
    DEFAULT_FILE_LOC_THRESHOLD,
    collect_sources,
    compute,
    count_loc,
)
from erosion.models import GodClass, GodFile, MassFinding


def _class_source(name: str, methods: int, body_lines_per_method: int = 1) -> str:
    lines = [f"class {name}:"]
    for i in range(methods):
        lines.append(f"    def m{i}(self):")
        lines.extend(["        x = 1"] * body_lines_per_method)
    return "\n".join(lines) + "\n"


# --- count_loc ---------------------------------------------------------------


def test_count_loc_ignores_blank_and_comment_only_lines() -> None:
    text = "import os\n\n# a comment\nx = 1  # trailing comment counts\n   \n"
    assert count_loc(text) == 2


# --- compute: files ----------------------------------------------------------


def test_file_at_threshold_is_a_god_file() -> None:
    big = "x = 1\n" * 10
    small = "x = 1\n" * 9
    finding = compute({"big.py": big, "small.py": small}, file_loc_threshold=10)
    assert finding.god_files == (GodFile(path="big.py", loc=10),)
    assert finding.total_files == 2


def test_god_files_sorted_by_loc_desc_then_path() -> None:
    srcs = {"b.py": "x = 1\n" * 5, "a.py": "x = 1\n" * 5, "c.py": "x = 1\n" * 7}
    finding = compute(srcs, file_loc_threshold=5)
    assert [g.path for g in finding.god_files] == ["c.py", "a.py", "b.py"]


# --- compute: classes --------------------------------------------------------


def test_class_flagged_by_method_count() -> None:
    src = _class_source("Hub", methods=4)
    finding = compute(
        {"hub.py": src}, class_loc_threshold=10_000, class_method_threshold=4
    )
    assert len(finding.god_classes) == 1
    gc = finding.god_classes[0]
    assert gc == GodClass(path="hub.py", name="Hub", loc=9, methods=4)
    assert gc.key == "hub.py:Hub"


def test_class_flagged_by_loc() -> None:
    src = _class_source("Fat", methods=2, body_lines_per_method=5)
    finding = compute(
        {"fat.py": src}, class_loc_threshold=13, class_method_threshold=999
    )
    assert [c.name for c in finding.god_classes] == ["Fat"]


def test_class_below_both_thresholds_is_not_flagged() -> None:
    src = _class_source("Lean", methods=2)
    finding = compute(
        {"lean.py": src}, class_loc_threshold=50, class_method_threshold=10
    )
    assert finding.god_classes == ()
    assert finding.is_empty


def test_nested_class_is_measured_independently() -> None:
    src = "class Outer:\n    class Inner:\n" + "".join(
        f"        def m{i}(self):\n            pass\n" for i in range(3)
    )
    finding = compute(
        {"n.py": src}, class_loc_threshold=10_000, class_method_threshold=3
    )
    assert [c.name for c in finding.god_classes] == ["Inner"]


def test_unparseable_file_counts_loc_but_yields_no_classes() -> None:
    broken = "class Broken(:\n" + "x = 1\n" * 4
    finding = compute({"broken.py": broken}, file_loc_threshold=5)
    assert finding.god_files == (GodFile(path="broken.py", loc=5),)
    assert finding.god_classes == ()


def test_god_classes_sorted_by_loc_desc_then_key() -> None:
    a = _class_source("A", methods=3, body_lines_per_method=2)  # 10 loc
    b = _class_source("B", methods=3, body_lines_per_method=1)  # 7 loc
    finding = compute(
        {"z.py": a, "y.py": b}, class_loc_threshold=1, class_method_threshold=999
    )
    assert [c.key for c in finding.god_classes] == ["z.py:A", "y.py:B"]


def test_finding_records_thresholds() -> None:
    finding = compute({})
    assert isinstance(finding, MassFinding)
    assert finding.file_loc_threshold == DEFAULT_FILE_LOC_THRESHOLD
    assert finding.class_loc_threshold == DEFAULT_CLASS_LOC_THRESHOLD
    assert finding.class_method_threshold == DEFAULT_CLASS_METHOD_THRESHOLD


# --- collect_sources ---------------------------------------------------------


def test_collect_sources_skips_ui_node_modules_and_pycache(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "a.py").write_text("x = 1\n")
    (src / "top.py").write_text("y = 2\n")
    (src / "ui" / "x").mkdir(parents=True)
    (src / "ui" / "x" / "skip.py").write_text("z = 3\n")
    (src / "pkg" / "node_modules").mkdir()
    (src / "pkg" / "node_modules" / "skip.py").write_text("z = 3\n")
    (src / "pkg" / "__pycache__").mkdir()
    (src / "pkg" / "__pycache__" / "skip.py").write_text("z = 3\n")
    (src / "pkg" / "notes.txt").write_text("not python\n")

    sources = collect_sources(src)

    assert sources == {"src/pkg/a.py": "x = 1\n", "src/top.py": "y = 2\n"}
