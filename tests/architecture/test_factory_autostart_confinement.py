"""Structural gate: boot-time autostart (#11208) is called ONLY from
``src/server.py`` — never from MockWorld or the sandbox docker entrypoint.

The spec requires autostart to "never autostart" under MockWorld/sandbox
contexts. Those two harnesses each boot a ``HydraFlowDashboard`` directly
(``mockworld/sandbox_main.py``'s ``main()``, and
``tests/scenarios/fakes/mock_world.py``'s ``MockWorld.start_dashboard``),
bypassing ``server.py``'s boot sequence entirely — so the guarantee is
structural, not a runtime flag. This gate makes a future call site added to
either harness (or to any other production module) a hard-fail, mirroring
``tests/architecture/test_process_group_kill_guard.py``'s "guarded primitive"
pattern for ``os.killpg``.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SRC = REPO_ROOT / "src"

_ALLOWED = {"server.py"}

_TARGET = "maybe_autostart_host"

# Boot entrypoints the spec explicitly calls out as "never autostart here" —
# checked by simple substring absence rather than AST, since the guarantee we
# want is "doesn't even reference the function", not just "doesn't call it"
# (e.g. no `from factory_autostart import ...` either).
_MUST_NOT_MENTION = (
    SRC / "mockworld" / "sandbox_main.py",
    REPO_ROOT / "tests" / "scenarios" / "fakes" / "mock_world.py",
)


def _calls_to(tree: ast.AST, name: str) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Name)
            and func.id == name
            or isinstance(func, ast.Attribute)
            and func.attr == name
        ):
            lines.append(node.lineno)
    return lines


def test_maybe_autostart_host_only_called_from_server_py() -> None:
    offenders: list[str] = []
    for py in sorted(SRC.rglob("*.py")):
        if py.name in _ALLOWED or py.name == "factory_autostart.py":
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for lineno in _calls_to(tree, _TARGET):
            offenders.append(f"{py.relative_to(SRC)}:{lineno}")
    assert not offenders, (
        f"{_TARGET} called outside server.py: {offenders}. Boot-time "
        "autostart (#11208) must fire from exactly one production call "
        "site — server.py's _boot_factory — never from a caretaker loop, "
        "route, or other module."
    )


def test_server_py_still_calls_maybe_autostart_host() -> None:
    """Guard the guard: an empty allowlist match must not silently pass."""
    tree = ast.parse((SRC / "server.py").read_text())
    assert _calls_to(tree, _TARGET), "server.py no longer calls maybe_autostart_host?"


def test_mockworld_and_sandbox_entrypoints_never_mention_autostart() -> None:
    """MockWorld/sandbox boot a dashboard directly, bypassing server.py.

    A plain substring check (not just an AST call check) so even a stray
    ``from factory_autostart import ...`` — not only a call — trips this.
    """
    offenders: list[str] = []
    for path in _MUST_NOT_MENTION:
        text = path.read_text(encoding="utf-8", errors="replace")
        if "factory_autostart" in text or _TARGET in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        f"Boot entrypoints reference factory autostart: {offenders}. "
        "MockWorld and the sandbox docker entrypoint must never autostart "
        "(#11208) — they boot a dashboard directly and must stay ignorant "
        "of factory_autostart entirely."
    )
