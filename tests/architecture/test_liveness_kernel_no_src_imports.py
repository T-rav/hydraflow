"""Architecture guard: the liveness kernel's decision cores are stdlib-only (#10734).

The Tier-1 liveness kernel is the error kernel that restarts everything else. A
kernel that imports ``src/`` (the thing it watches) cannot run when that thing is
broken — a missing dependency or a syntax error from a bad deploy would take the
watchdog down with the factory. This AST scan pins the contract: every module
under ``scripts/liveness/`` may import only the standard library (plus the
``scripts.liveness`` package itself). A future edit that reaches into ``src`` —
directly or via a top-level HydraFlow module — fails here.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIVENESS_DIR = _REPO_ROOT / "scripts" / "liveness"

# Top-level modules the kernel is allowed to import: the standard library, plus
# its own package. Anything else (config, orchestrator, models, git_revision, …)
# is a HydraFlow/src module and is forbidden.
_ALLOWED_ROOTS = frozenset(sys.stdlib_module_names) | {"scripts"}


def _top_level_imports(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            # Relative imports (level > 0) resolve within scripts.liveness itself.
            if node.level and node.level > 0:
                roots.add("scripts")
            elif node.module:
                roots.add(node.module.split(".", 1)[0])
    return roots


def test_liveness_dir_exists_and_has_modules() -> None:
    modules = list(_LIVENESS_DIR.glob("*.py"))
    assert modules, "scripts/liveness/ has no modules — did the package move?"


def test_every_liveness_module_imports_only_stdlib() -> None:
    offenders: dict[str, set[str]] = {}
    for module in sorted(_LIVENESS_DIR.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        forbidden = _top_level_imports(tree) - _ALLOWED_ROOTS
        if forbidden:
            offenders[module.name] = forbidden
    assert not offenders, (
        "scripts/liveness/ modules must import only the standard library — the "
        f"error kernel must not import src/. Forbidden imports: {offenders}"
    )
