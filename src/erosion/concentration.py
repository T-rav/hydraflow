"""Pure concentration (fan-in / god-file) sensor — the counter-metric to spread.

``erosion.spread`` measures *one change spanning many modules* (shotgun surgery).
Its missing pair, which #10840 ("no instrument ships alone") says must exist, is
the mirror failure mode: *one module that many modules depend on* — a god-file
every change routes through. This sensor supplies it.

**Granularity matters.** The arch module graph (``arch.extractors.modules``) is
*package*-level, so the flat top-level ``src/*.py`` files — where HydraFlow's real
god-files live (``models`` @167 importers, ``config`` @157) — all collapse into a
single ``src`` node and vanish. So concentration is computed on a **file-level**
import graph (:func:`extract_file_import_graph`), where each ``src`` module is its
own node and fan-in is the count of distinct modules importing it.

Purity contract mirrors ``erosion.spread``: :func:`compute` is pure over a
``ModuleGraph`` value (no repo root, no I/O). The impure AST extraction lives in
:func:`extract_file_import_graph`, the file-level analog of
``arch.extractors.modules.extract_module_graph`` and the sibling of
``erosion.spread.changed_files_for_range``.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

from arch._models import ModuleEdge, ModuleGraph, ModuleNode
from erosion.models import ConcentrationFinding, GodModule

#: Fan-in at or above this many distinct dependents makes a module a god-file.
#: Calibrated on the live file-level graph, which has a clean break: a god-cluster
#: at fan-in ≥51 (models 167, config 157, exception_classify 81, base_background_loop
#: 66, events 64, state 63, ports 61, subprocess_util 53, dedup_store 51), then a
#: gap to pr_manager (34) and below. 40 isolates that cluster with margin on both
#: sides, so single-import churn near the line never trips the ratchet. The
#: baseline is what actually gates; this bounds the reported set.
DEFAULT_THRESHOLD = 40


def compute(
    module_graph: ModuleGraph, *, threshold: int = DEFAULT_THRESHOLD
) -> ConcentrationFinding:
    """Rank modules by fan-in; report those at or above *threshold*.

    Self-edges are ignored — a module importing itself is not a dependency of
    *other* code and must not inflate its god-ness. Edges into a target the graph
    does not list as a node are skipped rather than inventing a phantom god-file.
    """
    dependents: dict[str, set[str]] = defaultdict(set)
    weighted: dict[str, int] = defaultdict(int)
    known = {node.name for node in module_graph.nodes}
    for edge in module_graph.edges:
        if edge.from_module == edge.to_module or edge.to_module not in known:
            continue
        dependents[edge.to_module].add(edge.from_module)
        weighted[edge.to_module] += edge.weight

    gods = [
        GodModule(module=mod, fan_in=len(deps), weighted_fan_in=weighted[mod])
        for mod, deps in dependents.items()
        if len(deps) >= threshold
    ]
    gods.sort(key=lambda g: (-g.fan_in, g.module))
    return ConcentrationFinding(
        god_modules=tuple(gods),
        threshold=threshold,
        total_modules=len(known),
    )


def _module_name(path: Path, src_dir: Path) -> str:
    """``src/config.py`` → ``config``; ``src/erosion/spread.py`` → ``erosion.spread``."""
    rel = path.relative_to(src_dir).with_suffix("")
    return ".".join(p for p in rel.parts if p != "__init__")


def extract_file_import_graph(src_dir: Path) -> ModuleGraph:
    """Build a FILE-level import graph of the ``src`` tree (impure — reads files).

    Nodes are per-file modules (``config``, ``models``, ``erosion.spread``, …);
    an edge ``A → B`` means file ``A`` imports local module ``B``. Only imports
    resolving to a local module are edged (stdlib/third-party are ignored), so
    fan-in on ``B`` counts exactly how many local files depend on it — the
    god-file signal.
    """
    files = [
        p
        for p in sorted(src_dir.rglob("*.py"))
        if "node_modules" not in p.parts and "__pycache__" not in p.parts
    ]
    local = {_module_name(p, src_dir) for p in files}
    edge_weights: dict[tuple[str, str], int] = defaultdict(int)
    for path in files:
        me = _module_name(path, src_dir)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                targets.append(node.module)
            elif isinstance(node, ast.Import):
                targets.extend(a.name for a in node.names)
            for target in targets:
                if target in local and target != me:
                    edge_weights[(me, target)] += 1
    return ModuleGraph(
        nodes=[ModuleNode(name=m) for m in sorted(local)],
        edges=[
            ModuleEdge(from_module=frm, to_module=to, weight=w)
            for (frm, to), w in sorted(edge_weights.items())
        ],
    )
