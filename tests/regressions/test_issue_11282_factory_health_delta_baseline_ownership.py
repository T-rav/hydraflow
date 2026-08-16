"""Regression test for the #11310 code-review fix (issue #11282).

Bug (backend half): ``factory_health.metric_metadata()`` originally hand-wrote
a ``delta_baseline`` string per tile describing a comparison
(``latest - first`` over the rolling-average series) that is actually
computed in the frontend, in ``FactoryHealthSection.jsx``'s ``MetricCard``,
over ``MetricCard``'s own ``values`` array. Two places describing the same
arithmetic drift apart the moment either one changes — exactly what the
#11118 falsifiability convention exists to prevent. The fix removed
``delta_baseline`` from ``metric_metadata()`` entirely and made
``MetricCard`` generate that line itself, from the array the delta is
actually computed from.

Bug (frontend half, same PR): ``CompanionGraphs`` used a hard ``Math.min``
across all five tiles' rolling-average series lengths and returned ``null``
for the WHOLE aligned-trend row if any single tile had fewer than 2 points —
so wiring up one new metric with sparse history blanked the trend graphs for
the other four metrics that had full history. That behavior is pinned in
``src/ui/src/components/diagnostics/__tests__/FactoryHealthSection.test.jsx``
(``does not blank the whole aligned-trend row when only one metric has a
sparse series``) — a Python regression test cannot exercise React rendering,
so this file only pins the backend contract described above.

This test fails loudly if ``delta_baseline`` (or any per-tile delta
description) creeps back into the backend metadata.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from factory_health import metric_metadata  # noqa: E402


def test_metric_metadata_never_describes_a_delta_baseline() -> None:
    meta = metric_metadata()
    assert meta, "metric_metadata() must describe at least one tile"
    for key, entry in meta.items():
        assert "delta_baseline" not in entry, (
            f"{key}: metric_metadata() must not re-introduce a "
            "delta_baseline description — the delta is computed (and "
            "described) in FactoryHealthSection.jsx's MetricCard, over its "
            "own `values` array. A backend string here would duplicate "
            "arithmetic this module can't see and would silently go stale "
            "the next time the frontend delta formula changes."
        )
