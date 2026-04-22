from __future__ import annotations

from arch.models import Allowlist, Fitness, ImportGraph, LayerMap, RuleModule
from arch.validator import validate


def _graph(edges: list[tuple[str, str]]) -> ImportGraph:
    g = ImportGraph(module_unit="file")
    for s, t in edges:
        g.add_edge(s, t)
    return g


def _rules(
    layers: LayerMap,
    allowlist: Allowlist | None = None,
    fitness: list[Fitness] | None = None,
) -> RuleModule:
    return RuleModule(
        extractor=lambda _: ImportGraph(module_unit="file"),
        layers=layers,
        allowlist=allowlist or Allowlist({}),
        fitness=fitness or [],
    )


def test_valid_downward_edge_passes() -> None:
    layers = LayerMap({"src/app/**": 2, "src/domain/**": 1})
    assert validate(_graph([("src/app/a.py", "src/domain/b.py")]), _rules(layers)) == []


def test_upward_edge_is_a_violation() -> None:
    layers = LayerMap({"src/app/**": 2, "src/domain/**": 1})
    vs = validate(_graph([("src/domain/b.py", "src/app/a.py")]), _rules(layers))
    assert len(vs) == 1
    assert vs[0].rule == "layer"


def test_allowlist_suppresses_violation() -> None:
    layers = LayerMap({"src/app/**": 2, "src/runner/**": 3})
    al = Allowlist({"src/app/plan_phase.py": {"src/runner/planner.py"}})
    vs = validate(
        _graph([("src/app/plan_phase.py", "src/runner/planner.py")]),
        _rules(layers, allowlist=al),
    )
    assert vs == []


def test_fitness_max_lines_violation(tmp_path) -> None:
    big = tmp_path / "big.py"
    big.write_text("x = 1\n" * 700)
    layers = LayerMap({f"{tmp_path.name}/**": 1})
    fit = [Fitness.max_lines(f"{tmp_path.name}/big.py", 600)]
    graph = _graph([])
    graph.nodes.add(f"{tmp_path.name}/big.py")
    vs = validate(graph, _rules(layers, fitness=fit), repo_root=tmp_path.parent)
    assert any(v.rule == "max_lines" for v in vs)


def test_unknown_layer_nodes_are_ignored() -> None:
    layers = LayerMap({"src/app/**": 2})
    vs = validate(_graph([("vendored/x.py", "src/app/a.py")]), _rules(layers))
    assert vs == []
