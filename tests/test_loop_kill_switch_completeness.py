"""Factory validation: every background loop has the ADR-0049 in-body kill-switch gate.

Auto-discovers ``BaseBackgroundLoop`` subclasses from every loop unit under
``src/`` — a ``*_loop.py`` module OR a ``*_loop/`` package
(``tests.loop_module_scan``, shared with ``test_loop_wiring_completeness.py``) —
and asserts each one's ``_do_work`` begins with the universal kill-switch gate::

    if not self._enabled_cb(self._worker_name):
        return {"status": "disabled"}

This is the enforcement net ``docs/wiki/dark-factory.md`` §5 advertises but which was
never actually committed. It is a *ratchet*: ``_GRANDFATHERED`` must stay empty. A new
loop that gates only on an env/config flag (the deprecated mechanism — operator intent
is a UI toggle, not env vars) fails this test instead of silently shipping an inert
System-tab toggle.

Ref: dark-factory hands-off audit (findings: no-killswitch-completeness-net,
four-env-only-loops-no-inbody-gate, diagram-loop-uncontrollable-from-ui).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.loop_module_scan import all_loop_classes, loop_classes, loop_text, loop_units

SRC = Path(__file__).resolve().parent.parent / "src"

# Ratchet allow-list. MUST stay empty — every loop is UI-kill-switchable, no exceptions
# (dark-factory.md §2.1.2). If a loop genuinely cannot host the gate, fixing the loop is
# the answer, not adding it here.
_GRANDFATHERED: frozenset[str] = frozenset()

_GATE_CALL = "self._enabled_cb(self._worker_name)"

# The gate reads ``_do_work`` out of the loop CLASS's own body, so a decomposed
# loop must keep ``_do_work`` in the class rather than in a mixin — otherwise
# this check finds nothing for that loop and passes vacuously.


def _loops_missing_inbody_gate() -> list[str]:
    """Return loop names whose loop class lacks the in-body kill-switch gate."""
    missing: list[str] = []
    for cls in all_loop_classes(SRC):
        dowork = next(
            (
                n
                for n in cls.node.body
                if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef)
                and n.name == "_do_work"
            ),
            None,
        )
        if dowork is None:
            # No _do_work in this class: it does not define a work cycle here.
            continue
        method_src = ast.get_source_segment(cls.text, dowork) or ""
        if _GATE_CALL not in method_src:
            missing.append(cls.loop_name)
    return [m for m in missing if m not in _GRANDFATHERED]


def test_every_loop_has_inbody_kill_switch_gate() -> None:
    missing = _loops_missing_inbody_gate()
    assert not missing, (
        "Loops missing the ADR-0049 in-body kill-switch gate "
        f"`if not {_GATE_CALL}: return {{'status': 'disabled'}}` in _do_work: "
        f"{sorted(set(missing))}. The UI toggle is inert for these loops — add the gate "
        "as the FIRST statement of _do_work (keep any env/config gate below as deploy-time "
        "defense-in-depth)."
    )


def test_grandfather_list_is_empty() -> None:
    """The ratchet only works if nobody quietly adds exemptions."""
    assert frozenset() == _GRANDFATHERED, (
        "_GRANDFATHERED must stay empty: every loop is UI-kill-switchable (no exceptions). "
        f"Found exemptions: {sorted(_GRANDFATHERED)}"
    )


def test_worker_names_are_underscore_canonical() -> None:
    """worker_name must be underscore-canonical (no hyphens).

    The kill-switch gate calls ``self._enabled_cb(self._worker_name)``, and the UI
    toggle / BGWorkerManager / orchestrator registry / worker_catalog / constants.js
    all key the loop by an *underscore* name. A hyphenated worker_name (the historical
    ``diagram-loop`` bug) silently never matches that key, so flipping the System-tab
    toggle is a no-op — ``is_enabled('diagram-loop')`` returns the True default forever.
    This guards the regression at its source for every loop.
    """
    offenders: dict[str, str] = {}
    worker_re = re.compile(r"""worker_name\s*=\s*["']([\w-]+)["']""")
    for unit in loop_units(SRC):
        if not loop_classes(unit):
            continue
        for match in worker_re.finditer(loop_text(unit)):
            name = match.group(1)
            if "-" in name:
                offenders[unit.stem] = name
    assert not offenders, (
        "worker_name values must be underscore-canonical to match the registry/UI keys "
        f"the kill-switch toggle uses (hyphens make the toggle inert): {offenders}"
    )
