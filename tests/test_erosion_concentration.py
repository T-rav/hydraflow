"""Unit tests for the concentration (fan-in / god-file) sensor (#10840)."""

from __future__ import annotations

from pathlib import Path

from arch._models import ModuleEdge, ModuleGraph, ModuleNode
from erosion.concentration import compute, extract_file_import_graph
from erosion.concentration_baseline import (
    ConcentrationBaseline,
    load_concentration_baseline,
    new_god_files,
    save_concentration_baseline,
    worsened,
)
from erosion.models import ConcentrationFinding


def _graph(edges: list[tuple[str, str, int]], nodes: list[str]) -> ModuleGraph:
    return ModuleGraph(
        nodes=[ModuleNode(name=n) for n in nodes],
        edges=[ModuleEdge(from_module=f, to_module=t, weight=w) for f, t, w in edges],
    )


# --- compute ----------------------------------------------------------------


def test_fan_in_counts_distinct_dependents() -> None:
    g = _graph(
        [("a", "hub", 1), ("b", "hub", 2), ("c", "hub", 1)],
        ["a", "b", "c", "hub"],
    )
    f = compute(g, threshold=2)
    assert len(f.god_modules) == 1
    hub = f.god_modules[0]
    assert hub.module == "hub"
    assert hub.fan_in == 3  # 3 distinct dependents
    assert hub.weighted_fan_in == 4  # 1+2+1


def test_below_threshold_is_not_a_god() -> None:
    g = _graph([("a", "x", 1)], ["a", "x"])
    assert compute(g, threshold=2).god_modules == ()


def test_self_edge_ignored() -> None:
    g = _graph([("x", "x", 5), ("a", "x", 1)], ["a", "x"])
    f = compute(g, threshold=1)
    assert f.god_modules[0].fan_in == 1  # the self-edge does not count


def test_edge_into_unknown_target_skipped() -> None:
    g = _graph([("a", "ghost", 1), ("b", "ghost", 1)], ["a", "b"])  # ghost not a node
    assert compute(g, threshold=1).god_modules == ()


def test_ranked_by_fan_in_desc_then_name() -> None:
    g = _graph(
        [("a", "big", 1), ("b", "big", 1), ("a", "small", 1)],
        ["a", "b", "big", "small"],
    )
    mods = [gm.module for gm in compute(g, threshold=1).god_modules]
    assert mods == ["big", "small"]


# --- extract_file_import_graph ----------------------------------------------


def test_extractor_builds_file_level_edges(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src).mkdir()
    (src / "hub.py").write_text("X = 1\n")
    (src / "a.py").write_text("from hub import X\n")
    (src / "b.py").write_text("import hub\n")
    (src / "c.py").write_text("import os\n")  # non-local — no edge
    g = extract_file_import_graph(src)
    f = compute(g, threshold=1)
    hub = next(gm for gm in f.god_modules if gm.module == "hub")
    assert hub.fan_in == 2  # a and b import hub; c imports stdlib only
    assert {n.name for n in g.nodes} == {"hub", "a", "b", "c"}


def test_extractor_names_nested_modules(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "__init__.py").write_text("")
    (src / "pkg" / "leaf.py").write_text("X = 1\n")
    (src / "user.py").write_text("from pkg.leaf import X\n")
    g = extract_file_import_graph(src)
    names = {n.name for n in g.nodes}
    assert "pkg.leaf" in names and "user" in names
    assert compute(g, threshold=1).god_modules[0].module == "pkg.leaf"


# --- baseline ---------------------------------------------------------------


def _finding(*mods: tuple[str, int]) -> ConcentrationFinding:
    from erosion.models import GodModule

    return ConcentrationFinding(
        god_modules=tuple(
            GodModule(module=m, fan_in=n, weighted_fan_in=n) for m, n in mods
        ),
        threshold=30,
        total_modules=100,
    )


def test_baseline_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "concentration.yaml"
    save_concentration_baseline(
        p, _finding(("models", 167), ("config", 157)), comment="x"
    )
    bl = load_concentration_baseline(p)
    assert bl.entries == {"models": 167, "config": 157}
    assert bl.comment == "x"


def test_load_missing_baseline_is_empty(tmp_path: Path) -> None:
    assert (
        load_concentration_baseline(tmp_path / "nope.yaml") == ConcentrationBaseline()
    )


def test_new_god_files_flags_only_unbaselined() -> None:
    finding = _finding(("models", 167), ("newgod", 40))
    baseline = ConcentrationBaseline(entries={"models": 167})
    assert [g.module for g in new_god_files(finding, baseline)] == ["newgod"]


def test_worsened_flags_growth_over_baseline() -> None:
    finding = _finding(("models", 180), ("config", 157))
    baseline = ConcentrationBaseline(entries={"models": 167, "config": 157})
    assert [g.module for g in worsened(finding, baseline)] == ["models"]
