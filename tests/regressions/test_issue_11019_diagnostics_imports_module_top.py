"""Regression for #11019: judge-calibration endpoint imports live at module top.

The judge-calibration diagnostics endpoint (#10836) originally imported
``judge_calibration`` and the ``escape.ledger`` symbols lazily *inside* the
handler, each carrying a ``# noqa: PLC0415`` suppression. The suppressions
ratchet (``test_disturbance_ratchet``) flagged the two un-baselined noqa and
blocked the PR. They were promoted to module top — matching the convention
that pure diagnostic-support modules (``finder_calibration``,
``judge_calibration``, ``escape.ledger``) import at the top of
``_diagnostics_routes``.

This pins the import *location* so a future re-lazy-ing can't silently
reintroduce the PLC0415 churn: the names must resolve as module-level
attributes, and the endpoint source must not carry the lazy-import lines.
"""

from __future__ import annotations

import inspect

from dashboard_routes import _diagnostics_routes as mod


def test_judge_calibration_deps_are_module_level_attributes() -> None:
    # `import judge_calibration as jc` + `from escape.ledger import ...` at the
    # top of the module bind these names at import time (not per-request).
    assert mod.jc.__name__ == "judge_calibration"
    assert mod.EscapeLedger.__name__ == "EscapeLedger"
    assert mod.ESCAPE_LEDGER_FILENAME == "escape_ledger.jsonl"


def test_endpoint_source_has_no_lazy_calibration_imports() -> None:
    # The two judge-calibration lazy imports that produced the un-baselined
    # PLC0415 suppressions must stay gone. (The module legitimately keeps other
    # baselined PLC0415 lazy imports for unrelated endpoints, so this pins only
    # the two lines this fix removed — not all PLC0415 in the file.)
    source = inspect.getsource(mod)
    assert "import judge_calibration as jc  # noqa: PLC0415" not in source
    assert (
        "from escape.ledger import ESCAPE_LEDGER_FILENAME, EscapeLedger"
        "  # noqa: PLC0415" not in source
    )
