"""Regression: clearing the audit check registry for test isolation must restore it.

Issue #10499 — ``tests/test_hydraflow_audit_runner.py``'s ``_isolate_registry``
autouse fixture called ``registry._clear_for_tests()`` at both setup AND
teardown, leaving the process-global ``_REGISTRY`` permanently empty for the
rest of the worker's test run. ``@register(...)`` decorators only fire once,
at first import of a check module, so nothing ever repopulated it — any
later test on the same xdist worker that called ``registry.get("P10.3")``
(or any other real check id) got ``None``. This is exactly how
``tests/regressions/test_p103_excludes_test_only_fix_commits.py`` failed in
``make quality``'s parallel run: deterministically, once a worker happened
to run the two files in that order — reruns did not rescue it, because it
is a persistent leak, not a timing flake.

The fix: snapshot the registry before clearing it, and restore that
snapshot (not another blind clear) on teardown. This test pins that the
snapshot/restore pair actually round-trips real registrations through a
clear, reproducing the exact sequence the buggy fixture performed.
"""

from __future__ import annotations

from scripts.hydraflow_audit import registry
from scripts.hydraflow_audit.checks import p10_tdd  # noqa: F401 -- registers P10.3


def test_registry_snapshot_restore_survives_a_clear() -> None:
    real_check = registry.get("P10.3")
    assert real_check is not None

    snapshot = registry._snapshot_for_tests()
    registry._clear_for_tests()
    assert registry.get("P10.3") is None  # cleared, as the isolating fixture wants

    registry._restore_for_tests(snapshot)

    assert registry.get("P10.3") is real_check
