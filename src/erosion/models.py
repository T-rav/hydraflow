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
class DuplicationFinding:
    """Near-duplicate block density across a set of files — the sensor's reading.

    v2 of epic #10104 (#10367): the duplication-density signal `erosion.scatter`
    v1 explicitly deferred (see that module's docstring). ``duplicated_blocks``
    counts normalized N-line windows that appear in two or more places;
    ``total_lines`` is the non-blank line total the density is taken over.
    Same purity contract as `erosion.spread.compute`: pure over explicit file
    contents, no git dependency in the core.
    """

    duplicated_blocks: int
    total_lines: int
    block_lines: int
    duplicate_groups: tuple[tuple[str, ...], ...] = ()  # sorted file-sets per group

    @property
    def total_kloc(self) -> float:
        """Thousands of non-blank lines the density is measured over."""
        return self.total_lines / 1000.0

    @property
    def density(self) -> float:
        """Duplicated blocks per KLOC; 0.0 when nothing was measured."""
        if self.total_lines == 0:
            return 0.0
        return self.duplicated_blocks / self.total_kloc


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


@dataclass(frozen=True)
class GodModule:
    """One high-fan-in module — a concentration (god-file) reading.

    ``fan_in`` is the count of DISTINCT modules that import this one (its
    dependents); ``weighted_fan_in`` sums the import-statement weights across
    those edges. High fan-in is the concentration failure mode — the mirror of
    ``SpreadFinding``'s shotgun surgery: one module every change must route
    through, rather than one change spanning many modules.
    """

    module: str
    fan_in: int  # distinct dependent modules
    weighted_fan_in: int  # sum of edge weights (import statements) into the module


@dataclass(frozen=True)
class ConcentrationFinding:
    """The repo-wide concentration reading — the counter-metric to spread (#10840).

    ``god_modules`` holds only modules whose ``fan_in`` met or exceeded
    ``threshold`` (sorted by fan_in desc, then name). This is a whole-graph
    property, not change-scoped: a god-file is defined by how much of the
    codebase depends on it, so ``compute`` reads the full module graph rather
    than a change's file list. ``max_fan_in`` is the concentration high-water
    mark used for the scalar ratchet.
    """

    god_modules: tuple[GodModule, ...]
    threshold: int
    total_modules: int

    @property
    def max_fan_in(self) -> int:
        return self.god_modules[0].fan_in if self.god_modules else 0

    @property
    def is_flagged(self) -> bool:
        """True when at least one module met the god-file threshold."""
        return len(self.god_modules) > 0
