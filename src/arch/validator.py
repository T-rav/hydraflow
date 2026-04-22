from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from arch.models import ImportGraph, LayerMap, RuleModule, Violation


def _match_layer(path: str, layers: LayerMap) -> object | None:
    for pattern, layer in layers.mapping.items():
        if fnmatch.fnmatchcase(path, pattern):
            return layer
    return None


def _match_any(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern)


def validate(
    graph: ImportGraph,
    rules: RuleModule,
    *,
    repo_root: Path | None = None,
) -> list[Violation]:
    violations: list[Violation] = []

    for source, target in sorted(graph.edges):
        src_layer = _match_layer(source, rules.layers)
        tgt_layer = _match_layer(target, rules.layers)
        if src_layer is None or tgt_layer is None:
            continue
        if isinstance(src_layer, int) and isinstance(tgt_layer, int):
            if tgt_layer > src_layer and not rules.allowlist.allowed(source, target):
                violations.append(
                    Violation(
                        source=source,
                        target=target,
                        rule="layer",
                        detail=f"layer {src_layer} → layer {tgt_layer} (upward)",
                    )
                )
        elif src_layer != tgt_layer and not rules.allowlist.allowed(source, target):
            violations.append(
                Violation(
                    source=source,
                    target=target,
                    rule="layer",
                    detail=f"layer {src_layer!r} → layer {tgt_layer!r} (cross-tier)",
                )
            )

    fan_out: dict[str, int] = {}
    fan_in: dict[str, int] = {}
    for s, t in graph.edges:
        fan_out[s] = fan_out.get(s, 0) + 1
        fan_in[t] = fan_in.get(t, 0) + 1

    for fit in rules.fitness:
        fit.validate_against(rules.layers)
        matching_nodes = [n for n in graph.nodes if _match_any(n, fit.target)]
        if fit.kind == "max_lines":
            if repo_root is None:
                continue
            for node in matching_nodes:
                p = repo_root / node
                if not p.is_file():
                    continue
                line_count = sum(1 for _ in p.open(encoding="utf-8", errors="ignore"))
                if line_count > int(fit.value):
                    violations.append(
                        Violation(node, "", "max_lines", f"{line_count} > {fit.value}")
                    )
        elif fit.kind == "max_fan_in":
            for node in matching_nodes:
                if fan_in.get(node, 0) > int(fit.value):
                    violations.append(
                        Violation(
                            node, "", "max_fan_in", f"{fan_in[node]} > {fit.value}"
                        )
                    )
        elif fit.kind == "max_fan_out":
            for node in matching_nodes:
                if fan_out.get(node, 0) > int(fit.value):
                    violations.append(
                        Violation(
                            node, "", "max_fan_out", f"{fan_out[node]} > {fit.value}"
                        )
                    )
        elif fit.kind == "forbidden_symbol":
            if repo_root is None or fit.pattern is None:
                continue
            rx = re.compile(fit.pattern)
            for node in matching_nodes:
                node_layer = _match_layer(node, rules.layers)
                if fit.outside_layer is not None and node_layer == fit.outside_layer:
                    continue
                p = repo_root / node
                if not p.is_file():
                    continue
                text = p.read_text(encoding="utf-8", errors="ignore")
                if rx.search(text):
                    violations.append(
                        Violation(node, "", "forbidden_symbol", fit.pattern)
                    )
        elif fit.kind == "naming_pattern":
            if fit.pattern is None:
                continue
            rx = re.compile(fit.pattern)
            for node in matching_nodes:
                name = Path(node).name
                if not rx.search(name):
                    violations.append(
                        Violation(
                            node,
                            "",
                            "naming_pattern",
                            f"{name} does not match {fit.pattern}",
                        )
                    )

    return violations
