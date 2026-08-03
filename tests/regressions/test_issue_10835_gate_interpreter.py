"""Regression for #10835: mutation-gauntlet gate commands must be spawnable.

Dogfooding the first campaign surfaced two gates ERRORING (never running):
their ``GATE_COMMANDS`` entries invoked bare ``python``, which is not reliably
on PATH (nor in a scratch worktree), so ``subprocess.run`` raised and the gate
was scored ``ERRORED`` instead of actually testing the mutant. A gate that
cannot spawn is invisible to the very kill-rate the instrument exists to
measure, so pin the launcher: every gate command must start with a resolvable
launcher (``make`` or ``uv``), never a bare interpreter.

The dict is extracted statically with ``ast`` — importing the shell module is
unreliable (it shares the name ``mutation_gauntlet`` with the pure core in
``src`` and does its own ``sys.path`` setup), and static extraction needs no
runtime environment.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Resolvable process launchers: `make` (targets set PYTHONPATH + uv) and `uv run`
# (the repo's canonical interpreter). A bare `python`/`python3` is NOT allowed —
# it is the exact spawn failure this regression guards against.
_ALLOWED_LAUNCHERS = {"make", "uv"}
_BANNED_LAUNCHERS = {"python", "python3"}


def _gate_commands() -> dict[str, list[str]]:
    """Statically extract the ``GATE_COMMANDS`` dict literal from the shell."""
    script = Path(__file__).resolve().parents[2] / "scripts" / "mutation_gauntlet.py"
    tree = ast.parse(script.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        # `GATE_COMMANDS: dict[...] = {...}` is an annotated assignment.
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "GATE_COMMANDS" and node.value is not None:
                return ast.literal_eval(node.value)
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "GATE_COMMANDS" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("GATE_COMMANDS not found in scripts/mutation_gauntlet.py")


def test_no_gate_command_uses_a_bare_interpreter() -> None:
    for gate, command in _gate_commands().items():
        assert command, f"gate {gate!r} has an empty command"
        assert command[0] not in _BANNED_LAUNCHERS, (
            f"gate {gate!r} launches bare {command[0]!r} — not reliably on PATH; "
            f"run through 'make' or 'uv run' so the gate actually executes"
        )


def test_every_gate_command_starts_with_a_resolvable_launcher() -> None:
    commands = _gate_commands()
    assert commands, "no gate commands defined"
    for gate, command in commands.items():
        assert command[0] in _ALLOWED_LAUNCHERS, (
            f"gate {gate!r} starts with {command[0]!r}; expected one of "
            f"{sorted(_ALLOWED_LAUNCHERS)} so it spawns in a scratch worktree"
        )
