"""Guard: ``src`` must not import ``scripts`` at module-import (boot) time (#10365).

The factory container (``Dockerfile.agent``) copies only ``src``, ``tests``,
``templates`` and ``static`` into the image and runs
``PYTHONPATH=/opt/hydraflow/src:/opt/hydraflow`` — ``scripts/`` is **absent** in
the image. So any ``src`` module that imports ``scripts`` *at module top level*
raises ``ModuleNotFoundError: No module named 'scripts'`` the instant it is
imported, crashing the container on boot. That is exactly how #10365 broke
staging: ``src/close_verification.py`` did
``from scripts.hydraflow_audit.false_close import ...`` at module scope, so
importing ``post_merge_handler`` (which imports it) exited the container with
status 1. The unit/audit suites missed it because they run with the repo ROOT on
``sys.path`` where ``scripts`` *is* importable — this guard closes that blind
spot with a container-faithful static check.

Scope — this flags only *import-time* ``scripts`` imports, the boot-breaker
class. It deliberately permits two patterns that never run at boot:

* ``if TYPE_CHECKING:`` imports — type-only, elided at runtime.
* Function/method-local (lazy) imports — run only when that function is called,
  not when the module is imported (e.g. the ADR-0082 gate-activation bridge in
  ``src/gate_activation_check.py`` imports ``scripts.gates`` inside its body).

If you need ``scripts`` code from ``src`` at import time, move the shared code
into ``src`` (as #10365 did with ``false_close``). ``src`` ships in the image;
``scripts`` does not.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"


def _is_type_checking_test(test: ast.expr) -> bool:
    """True for ``TYPE_CHECKING`` / ``typing.TYPE_CHECKING`` guard conditions."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _imports_scripts(node: ast.stmt) -> bool:
    """True when *node* imports the top-level ``scripts`` package."""
    if isinstance(node, ast.Import):
        return any(
            alias.name == "scripts" or alias.name.startswith("scripts.")
            for alias in node.names
        )
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        return node.level == 0 and (
            module == "scripts" or module.startswith("scripts.")
        )
    return False


def _boot_time_scripts_imports(body: list[ast.stmt]) -> list[ast.stmt]:
    """Collect ``scripts`` imports reachable at module-import (boot) time.

    Descends every block that executes when the module is imported — class
    bodies, ``if``/``for``/``while``/``with``/``try`` — but never a function or
    lambda body (deferred until called) nor the body of an ``if TYPE_CHECKING:``
    guard (elided at runtime).
    """
    offenders: list[ast.stmt] = []

    def walk(stmts: list[ast.stmt]) -> None:
        for node in stmts:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue  # body runs only when the function is called
            if _imports_scripts(node):
                offenders.append(node)
                continue
            if isinstance(node, ast.If):
                if _is_type_checking_test(node.test):
                    walk(node.orelse)  # type-only body skipped; else runs
                else:
                    walk(node.body)
                    walk(node.orelse)
                continue
            if isinstance(node, ast.For | ast.AsyncFor | ast.While):
                walk(node.body)
                walk(node.orelse)
                continue
            if isinstance(node, ast.With | ast.AsyncWith):
                walk(node.body)
                continue
            if isinstance(node, ast.Try):
                walk(node.body)
                for handler in node.handlers:
                    walk(handler.body)
                walk(node.orelse)
                walk(node.finalbody)
                continue
            if isinstance(node, ast.ClassDef):
                walk(node.body)  # class body executes at import
                continue

    walk(body)
    return offenders


def test_src_does_not_import_scripts_at_boot() -> None:
    offenders: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:  # pragma: no cover - surfaces a real parse break
            offenders.append(f"{path.relative_to(ROOT)}: unparseable ({exc})")
            continue
        for node in _boot_time_scripts_imports(tree.body):
            rel = path.relative_to(ROOT)
            offenders.append(f"{rel}:{node.lineno}: {ast.unparse(node)}")

    assert not offenders, (
        "src/ must NEVER import scripts/ at module-import (boot) time — the "
        "factory container ships src/ but not scripts/, so such an import "
        "crashes the container on boot (#10365). Move the shared code into src/, "
        "or defer the import into a function body / TYPE_CHECKING block if it is "
        "genuinely not needed at boot:\n  " + "\n  ".join(offenders)
    )
