"""Discover all sandbox scenarios under tests/sandbox_scenarios/scenarios/."""

from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path
from types import ModuleType


def load_all_scenarios(*, include_quarantined: bool = False) -> list[ModuleType]:
    """Import every s*.py module under tests/sandbox_scenarios/scenarios/.

    A scenario module may declare ``QUARANTINED = "#<issue>"`` to pull itself
    out of COLLECTIVE runs (run-all, the CI fast subset's parametrization)
    while a tracked defect makes its signal unreliable. Quarantined scenarios
    are skipped LOUDLY (one stderr line naming the tracking issue) so the gap
    in coverage is visible in every log, and they remain runnable one-off via
    ``sandbox_scenario.py run <name>`` / ``include_quarantined=True`` for
    debugging. The marker must die with its tracking issue — removing it is
    part of that issue's acceptance criteria.
    """
    import tests.sandbox_scenarios.scenarios as scenarios_pkg

    out: list[ModuleType] = []
    pkg_path = Path(scenarios_pkg.__file__).parent
    for _finder, name, _ispkg in pkgutil.iter_modules([str(pkg_path)]):
        if not name.startswith("s"):
            continue
        mod = importlib.import_module(f"tests.sandbox_scenarios.scenarios.{name}")
        marker = getattr(mod, "QUARANTINED", None)
        if marker and not include_quarantined:
            print(
                f"[scenario-loader] QUARANTINED scenario skipped: {name} "
                f"(tracking {marker})",
                file=sys.stderr,
            )
            continue
        out.append(mod)
    return sorted(out, key=lambda m: m.NAME)
