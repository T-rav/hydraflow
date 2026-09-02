"""The flow-stop key is named by its constant, never spelled (#11800 follow-on).

`flows/flow.py` defines `FLOW_STOP_KEY = "_stop"` and the canonical
`flow_stopped` guard reads `state.get(FLOW_STOP_KEY)`. That constant protected
nothing: every *writer* set `state["_stop"]` with the literal, so the readers
were tied to the constant and the writers to the string.

Changing `FLOW_STOP_KEY` would then desynchronise them **silently** — the guard
would look for the new key, twenty-five writers would keep setting the old one,
and every fail-closed early exit would stop firing while nothing raised. The
stop key is the fail-closed mechanism itself, so this is the worst place for a
constant that is merely advisory.

This is the "invert the rule" shape: rather than patching each spelling, the
gate makes naming the flow-stop key REQUIRE the owned constant. A literal
`"_stop"` outside the definition site is the defect, and adding a new writer
that spells it fails here.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"

#: The one module allowed to spell the key: where the constant is defined.
_OWNER = "src/flows/flow.py"

_LITERAL = "_stop"


def _spelled_sites() -> tuple[tuple[str, int], ...]:
    """Every string literal `"_stop"` outside the owning module."""
    sites = []
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC.parent).as_posix()
        if rel == _OWNER:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken file fails elsewhere
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == _LITERAL:
                sites.append((rel, node.lineno))
    return tuple(sites)


_SPELLED = _spelled_sites()


def test_the_owner_really_defines_the_constant() -> None:
    """Anti-vacuity: if the constant moved, this gate guards a dead name."""
    source = (_SRC / "flows" / "flow.py").read_text(encoding="utf-8")

    assert f'FLOW_STOP_KEY = "{_LITERAL}"' in source, (
        "FLOW_STOP_KEY is no longer defined here; this gate is exempting a "
        "module that no longer owns the key"
    )


def test_no_module_spells_the_flow_stop_key() -> None:
    """One assertion rather than one case per violation.

    The subject is empty when the rule holds, and a parametrised gate over an
    empty sequence *skips* — a green-looking result that says nothing. This
    fails loudly instead, and names every offender at once.
    """
    offenders = [f"{path}:{line}" for path, line in _SPELLED]

    assert not offenders, (
        f"these modules spell {_LITERAL!r} instead of importing FLOW_STOP_KEY "
        f"from flows.flow: {offenders}. The readers use the constant and the "
        f"writers use the string, so changing the constant would silently stop "
        f"every fail-closed early exit from firing."
    )
