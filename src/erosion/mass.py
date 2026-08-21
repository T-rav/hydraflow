"""Pure mass (size) sensor — god files and god classes by line count / method count.

The third god-file axis. ``erosion.concentration`` measures fan-in (how much of
the codebase depends on a module) and ``erosion.spread`` measures how far one
change ripples; neither sees a class that simply grew too large to hold in one
head. This sensor does: ``compute`` reads an explicit ``{path: text}`` mapping
(same purity contract as ``erosion.duplication.compute`` — no repo root, no
git, unit-testable with synthetic sources) and returns a ``MassFinding``.
``collect_sources`` is the thin filesystem adapter.

LOC is non-blank, non-comment lines — the count a reader actually has to hold.
A class is a god class when EITHER its LOC or its method count meets the
threshold; the two axes fail differently (a 600-line two-method class hides
complexity inside methods, a 40-method class has too many responsibilities)
and both resist safe decomposition.

Thresholds are module constants, not config (no second repo has asked for a
different setting yet; adding knobs ahead of need is the disturbance ADR-0104
warns about). The baseline module grandfathers today's offenders so the
ratchet only fires on NEW ones.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path

from erosion.models import GodClass, GodFile, MassFinding

#: Non-blank, non-comment lines at or above which a file is a god file.
DEFAULT_FILE_LOC_THRESHOLD = 1500
#: Class LOC at or above which a class is a god class.
DEFAULT_CLASS_LOC_THRESHOLD = 600
#: Direct method count at or above which a class is a god class.
DEFAULT_CLASS_METHOD_THRESHOLD = 40

_SKIP_DIRS = frozenset({"ui", "node_modules", "__pycache__", ".venv"})


def count_loc(text: str) -> int:
    """Count non-blank lines that are not comment-only."""
    total = 0
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped and not stripped.startswith("#"):
            total += 1
    return total


def _class_loc(text: str, node: ast.ClassDef) -> int:
    segment = ast.get_source_segment(text, node) or ""
    return count_loc(segment)


def _method_count(node: ast.ClassDef) -> int:
    return sum(
        1
        for child in node.body
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
    )


def compute(
    sources: Mapping[str, str],
    *,
    file_loc_threshold: int = DEFAULT_FILE_LOC_THRESHOLD,
    class_loc_threshold: int = DEFAULT_CLASS_LOC_THRESHOLD,
    class_method_threshold: int = DEFAULT_CLASS_METHOD_THRESHOLD,
) -> MassFinding:
    """Measure every source; report files and classes at or above the thresholds.

    Unparseable sources still contribute their file LOC (size is size) but no
    classes — the sensor never raises on bad input.
    """
    god_files: list[GodFile] = []
    god_classes: list[GodClass] = []
    for path, text in sources.items():
        loc = count_loc(text)
        if loc >= file_loc_threshold:
            god_files.append(GodFile(path=path, loc=loc))
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            cls_loc = _class_loc(text, node)
            methods = _method_count(node)
            if cls_loc >= class_loc_threshold or methods >= class_method_threshold:
                god_classes.append(
                    GodClass(path=path, name=node.name, loc=cls_loc, methods=methods)
                )
    god_files.sort(key=lambda g: (-g.loc, g.path))
    god_classes.sort(key=lambda c: (-c.loc, c.key))
    return MassFinding(
        god_files=tuple(god_files),
        god_classes=tuple(god_classes),
        total_files=len(sources),
        file_loc_threshold=file_loc_threshold,
        class_loc_threshold=class_loc_threshold,
        class_method_threshold=class_method_threshold,
    )


def collect_sources(src_dir: Path) -> dict[str, str]:
    """Read every ``.py`` under *src_dir* (impure), keyed by ``<src_dir.name>/<relative>`` posix path.

    Skips the dashboard's ``ui/`` tree, vendored ``node_modules``, bytecode
    caches and virtualenvs — none of them are HydraFlow Python the mass
    sensor should measure.
    """
    sources: dict[str, str] = {}
    for path in sorted(src_dir.rglob("*.py")):
        rel = path.relative_to(src_dir)
        if _SKIP_DIRS.intersection(rel.parts[:-1]):
            continue
        key = (Path(src_dir.name) / rel).as_posix()
        sources[key] = path.read_text(encoding="utf-8", errors="replace")
    return sources
