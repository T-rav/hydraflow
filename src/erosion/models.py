"""Core value objects for the erosion sensor family (epic #10104).

Mirrors `disturbance.models`' style (frozen dataclass, no behavior beyond a
derived property) for both the change-spread sensor (#10105) and the
concept-scatter sensor (#10106).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpreadFinding:
    """One change's file/module footprint — the sensor's raw reading.

    ``files_touched`` is the raw count of distinct changed files, mapped or
    not. ``modules_crossed`` counts only the DISTINCT modules successfully
    resolved via the arch module graph (`arch.extractors.modules.package_of`)
    — files outside `src/`, or whose derived package isn't a node the
    module graph actually knows about, land in ``unmapped_files`` instead.
    They are never silently dropped, but they also never inflate the
    module-spread signal with an unattributable path.
    """

    files_touched: int
    modules_crossed: int
    modules: tuple[str, ...]  # sorted, distinct modules spanned
    unmapped_files: tuple[str, ...]  # sorted; changed files with no known module

    @property
    def spread_ratio(self) -> float:
        """Modules crossed per file touched; 0.0 when nothing was touched.

        The shotgun-surgery signal: a change touching few files but
        spanning many modules for that size has a high ratio.
        """
        if self.files_touched == 0:
            return 0.0
        return self.modules_crossed / self.files_touched


@dataclass(frozen=True)
class ScatteredSymbol:
    """One newly-added identifier a change introduced into >= threshold distinct modules.

    v1 heuristic — PROVISIONAL, not the final definition (see
    `erosion.scatter` module docstring and epic #10104): the same new
    symbol name being independently introduced in several modules by one
    change, rather than defined once and shared, is treated as a
    shotgun-duplication / coupling-erosion smell.
    """

    symbol: str
    modules: tuple[str, ...]  # sorted, distinct modules the symbol was newly added to
    files: tuple[
        str, ...
    ]  # sorted, distinct changed files where the symbol was newly added


@dataclass(frozen=True)
class ScatterFinding:
    """One change's newly-added-symbol scatter footprint — the sensor's raw reading.

    ``scattered`` holds only symbols that met or exceeded ``threshold``
    distinct modules; a symbol newly added to 1-2 modules never appears
    here. ``unmapped_files`` mirrors `SpreadFinding`'s convention: changed
    files outside `src/`, or whose derived package isn't a known
    module-graph node, are tracked (not silently dropped) but never count
    toward any symbol's ``modules`` tally.
    """

    scattered: tuple[ScatteredSymbol, ...]  # sorted by symbol name
    threshold: int
    unmapped_files: tuple[str, ...]  # sorted

    @property
    def is_flagged(self) -> bool:
        """True when at least one symbol met the scatter threshold."""
        return len(self.scattered) > 0
