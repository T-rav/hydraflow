"""Structural gate: ``os.killpg`` lives ONLY in ``src/process_group.py``.

The guarded kill primitive exists because the mock-pid class was
independently re-derived three times in one night (#9648, #9911, the
#10002 CI smoke deaths): an unguarded ``os.killpg(proc.pid, ...)`` against
a test double coerces the mock pid to ``1`` via ``__index__`` — and a
pid-``0`` fake signals the CALLER'S OWN process group, killing the test
runner mid-suite with no step failure and no log flush. Point guards rot;
this gate makes a fourth re-derivation structurally impossible: any new
call site must route through ``process_group.kill_process_group``.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent.parent / "src"

_ALLOWED = {"process_group.py"}


def _killpg_calls(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "killpg"
            and isinstance(func.value, ast.Name)
            and func.value.id == "os"
        ):
            lines.append(node.lineno)
    return lines


def test_os_killpg_only_in_the_guarded_primitive() -> None:
    offenders: list[str] = []
    for py in sorted(SRC.rglob("*.py")):
        if py.name in _ALLOWED:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for lineno in _killpg_calls(tree):
            offenders.append(f"{py.relative_to(SRC)}:{lineno}")
    assert not offenders, (
        f"os.killpg called outside process_group.py: {offenders}. "
        "Route through process_group.kill_process_group — the guard there "
        "(real positive int pid, bool excluded, child-only fallback for "
        "fakes) is load-bearing; see the module docstring for the incident "
        "history."
    )


def test_the_primitive_itself_still_calls_killpg() -> None:
    """Guard the guard: an empty allowlist match must not silently pass."""
    tree = ast.parse((SRC / "process_group.py").read_text())
    assert _killpg_calls(tree), "process_group.py no longer calls os.killpg?"
