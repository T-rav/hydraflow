"""Regression pin for issue #10402: `_GIT_TIMEOUT_S` scatter across modules.

The concept-scatter sensor (#10106) flagged a single merged change that
independently introduced ``_GIT_TIMEOUT_S = 60`` in three modules; a
follow-up triage found the same byte-identical constant duplicated across
seven read-only git adapters:

- ``audit.detect``
- ``escape.detect``
- ``escape_ledger_loop``
- ``erosion.scatter``
- ``erosion.spread``
- ``erosion_metrics_loop``
- ``arch.generators.traceability_matrix``

#10402 consolidated all seven into one shared leaf constant,
``git_timeouts.GIT_READONLY_TIMEOUT_S``. This pin fails if a future change
reintroduces a local ``_GIT_TIMEOUT_S`` module constant in any of the seven
call sites (the scatter coming back), or if it collapses one of the two
*deliberately distinct* git timeout tiers (fast-fail status endpoint, heavy
audit git call) into the shared constant — those stay separate per
``git_timeouts``'s own docstring and ``tests/regressions/test_issue_9555.py``.
"""

from __future__ import annotations

import importlib
import inspect

import git_timeouts

# The seven modules #10402 consolidated onto git_timeouts.GIT_READONLY_TIMEOUT_S.
_CONSOLIDATED_MODULES = [
    "audit.detect",
    "escape.detect",
    "escape_ledger_loop",
    "erosion.scatter",
    "erosion.spread",
    "erosion_metrics_loop",
    "arch.generators.traceability_matrix",
]


def test_shared_constant_value_unchanged() -> None:
    """The consolidated value must preserve the pre-#10402 behaviour."""
    assert git_timeouts.GIT_READONLY_TIMEOUT_S == 60


def test_no_module_redefines_git_timeout_s() -> None:
    """A local `_GIT_TIMEOUT_S` module constant in any of the seven call
    sites is the scatter coming back."""
    for module_name in _CONSOLIDATED_MODULES:
        module = importlib.import_module(module_name)
        assert not hasattr(module, "_GIT_TIMEOUT_S"), (
            f"{module_name}._GIT_TIMEOUT_S is back — #10402 consolidated "
            f"this onto git_timeouts.GIT_READONLY_TIMEOUT_S; do not "
            f"reintroduce a local module constant"
        )


def test_all_consolidated_modules_import_shared_constant() -> None:
    """Each call site must actually reference the shared constant, not just
    happen to lack a local shadow."""
    for module_name in _CONSOLIDATED_MODULES:
        module = importlib.import_module(module_name)
        src = inspect.getsource(module)
        assert "GIT_READONLY_TIMEOUT_S" in src, (
            f"{module_name} no longer references "
            f"git_timeouts.GIT_READONLY_TIMEOUT_S — #10402's consolidation "
            f"was reverted without restoring a local timeout bound"
        )


def test_deliberately_distinct_tiers_are_not_collapsed() -> None:
    """The fast-fail and audit git tiers stay separate, separate-valued
    constants — they must NOT be unified with the read-only adapter tier."""
    import git_revision
    import principles_audit_loop

    assert git_revision._GIT_TIMEOUT_SECS == 5
    assert principles_audit_loop._GIT_TIMEOUT_SECONDS == 120
    assert git_timeouts.GIT_READONLY_TIMEOUT_S == 60

    values = {
        git_revision._GIT_TIMEOUT_SECS,
        principles_audit_loop._GIT_TIMEOUT_SECONDS,
        git_timeouts.GIT_READONLY_TIMEOUT_S,
    }
    assert len(values) == 3, (
        "the three git timeout tiers collapsed onto shared values — "
        "fast-fail (5s), read-only adapters (60s), and audit (120s) are "
        "deliberately distinct bounds for different call patterns"
    )
