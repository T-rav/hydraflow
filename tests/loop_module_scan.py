"""Package-aware discovery of the background loops the factory gates scan.

Every loop gate used to open with ``SRC.glob("*_loop.py")``. That is correct
only while a loop is exactly one file. The moment a loop is decomposed into a
package — ``src/health_monitor_loop/``, the shape ``review_phase/`` and
``implement_phase/`` already use, and the shape the mass roster (#11547) pushes
every oversized loop toward — the glob stops matching and the loop drops out of
the gate. Nothing goes red: the gate simply audits one fewer loop and stays
green, which is the worst possible failure mode for a ratchet.

Batch 3 of that roster hit the same class of hole in ``catalog_fake_methods``
(a non-recursive glob silently lost a decomposed fake from a parity catalog).
This module is the fix applied once, for every loop gate, so batches 5+ can
decompose ``staging_promotion_loop`` / ``repo_wiki_loop`` / the six others still
on the roster without re-opening it.

The unit of discovery is the LOOP, not the file: ``loop_units`` returns one
path per loop (a ``*_loop.py`` file or a ``*_loop/`` package directory) and
``loop_sources`` expands it to the files a content scan must read.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

_BASE = "BaseBackgroundLoop"


def loop_units(src: Path = SRC) -> list[Path]:
    """Every background loop under *src*, as the path that identifies it.

    A single-module loop is its ``*_loop.py``; a decomposed loop is its
    ``*_loop/`` package directory. Both answer ``.stem`` with the loop name.
    """
    units = list(src.glob("*_loop.py"))
    units += [d for d in src.glob("*_loop") if (d / "__init__.py").is_file()]
    return sorted(units)


def loop_sources(unit: Path) -> list[Path]:
    """The ``.py`` files that make up *unit* — what a content scan must read."""
    return [unit] if unit.is_file() else sorted(unit.rglob("*.py"))


def loop_source_files(src: Path = SRC) -> list[Path]:
    """Every ``.py`` file belonging to any loop, flattened."""
    return sorted(f for unit in loop_units(src) for f in loop_sources(unit))


@dataclass(frozen=True)
class LoopClass:
    """A ``BaseBackgroundLoop`` subclass, with the file it was parsed from."""

    unit: Path
    path: Path
    text: str
    node: ast.ClassDef

    @property
    def loop_name(self) -> str:
        return self.unit.stem


def _is_loop_class(node: ast.stmt) -> bool:
    if not isinstance(node, ast.ClassDef):
        return False
    return any(
        (getattr(b, "id", None) or getattr(b, "attr", None)) == _BASE
        for b in node.bases
    )


def loop_classes(unit: Path) -> list[LoopClass]:
    """The ``BaseBackgroundLoop`` subclasses defined anywhere in *unit*.

    AST-based on purpose. The old ``class\\s+(\\w+)\\s*\\(.*BaseBackgroundLoop.*\\)``
    regex is single-line, so a decomposed loop — whose class header spans
    several lines because it lists its mixins — matches nothing and is silently
    skipped.
    """
    found: list[LoopClass] = []
    for path in loop_sources(unit):
        text = path.read_text(encoding="utf-8")
        for node in ast.parse(text, filename=str(path)).body:
            if _is_loop_class(node):
                assert isinstance(node, ast.ClassDef)
                found.append(LoopClass(unit=unit, path=path, text=text, node=node))
    return found


def all_loop_classes(src: Path = SRC) -> list[LoopClass]:
    return [cls for unit in loop_units(src) for cls in loop_classes(unit)]


def loop_text(unit: Path) -> str:
    """*unit*'s whole source, concatenated — for plain substring/regex checks."""
    return "\n".join(p.read_text(encoding="utf-8") for p in loop_sources(unit))
