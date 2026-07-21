"""Core value objects for the change-spread sensor (#10105, epic #10104).

Mirrors `disturbance.models`' style (frozen dataclass, no behavior beyond a
derived property) for the erosion sensor family.
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
