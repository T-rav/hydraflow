"""#9543 — sandbox_main must not import the ``scripts`` package (any scope).

Dockerfile.agent ships only ``src``/``tests``/``templates``/``static`` into
the sandbox image; the repo-root ``scripts`` package does not exist there. A
module-level import crashes ``python -m mockworld.sandbox_main`` at boot for
EVERY scenario; a function-level one detonates at seam-wiring time for the
scenario that hits it. Both are invisible to host-tier tests (where
``scripts`` is importable) and only surface as a wedged docker lane — so the
constraint is pinned here, at the AST level, where a reintroduction reddens
in ``make quality``.

The seeded gate detector uses the duck-typed ``SeededActivationProposal``
mirror instead (GateActivatorLoop touches only the attributes; its own
``ActivationProposal`` import is TYPE_CHECKING-only).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

_SANDBOX_MAIN = (
    Path(__file__).resolve().parents[2] / "src" / "mockworld" / "sandbox_main.py"
)


def _scripts_imports(tree: ast.AST) -> list[tuple[int, str]]:
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders.extend(
                (node.lineno, alias.name)
                for alias in node.names
                if alias.name == "scripts" or alias.name.startswith("scripts.")
            )
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            module = node.module or ""
            if module == "scripts" or module.startswith("scripts."):
                offenders.append((node.lineno, module))
    return offenders


def test_sandbox_main_never_imports_scripts_package() -> None:
    tree = ast.parse(_SANDBOX_MAIN.read_text(encoding="utf-8"))

    offenders = _scripts_imports(tree)

    assert offenders == [], (
        f"src/mockworld/sandbox_main.py imports the `scripts` package at "
        f"{offenders} — that package is NOT shipped into the sandbox docker "
        "image (Dockerfile.agent copies only src/ and tests/), so "
        "the import wedges the air-gapped sandbox at boot or seam-wiring "
        "time. Use a duck-typed local stand-in instead (see "
        "SeededActivationProposal)."
    )


def test_seeded_gate_detector_needs_no_scripts_package() -> None:
    """The s66 seam builds proposals without the scripts package present."""
    import asyncio

    from mockworld.sandbox_main import build_seeded_gate_detector

    detector = build_seeded_gate_detector(
        [{"name": "g", "required_on": ["main"], "workflow": "t.yml", "job": "j"}]
    )
    was_loaded = {
        name: sys.modules.pop(name)
        for name in list(sys.modules)
        if name == "scripts" or name.startswith("scripts.")
    }
    try:
        proposals = asyncio.run(detector())
    finally:
        sys.modules.update(was_loaded)

    assert [p.name for p in proposals] == ["g"]
    assert proposals[0].required_on == ("main",)
