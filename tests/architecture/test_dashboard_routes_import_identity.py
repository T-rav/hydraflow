"""Guard (#10979): dashboard route modules import shared route symbols via ONE
canonical module path — never the bare ``_routes`` top-level spelling.

Every ``src/dashboard_routes/*.py`` consumes ``RouteContext`` (and the
``register(router, ctx)`` seam) from the package's ``_routes`` module. Under
``PYTHONPATH=src`` a module imported two ways is two distinct module objects:
``from dashboard_routes._routes import RouteContext`` (or the equivalent
relative ``from ._routes import RouteContext``) resolves to the SAME object,
but a bare ``from _routes import RouteContext`` / ``import _routes`` resolves to
a *different* top-level ``_routes`` module — two ``RouteContext`` class
identities, breaking ``isinstance`` and pyright assignability. That dual-import
-identity trap bit the ``_ws_stream`` extraction (#10978) and the #10874 class
of bugs; this AST guard (no imports — reads the on-disk tree) fails the build if
any route module reaches a shared symbol through the bare spelling, so a future
extraction can't silently reintroduce it.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Shared route symbols whose import spelling must stay canonical. Binding any of
# these from the bare top-level ``_routes`` module splits its class identity.
_GUARDED_NAMES = frozenset({"RouteContext", "register"})

# The bare top-level spellings that create a second module object.
_BARE_MODULES = frozenset({"_routes"})


def _routes_dir(repo_root: Path) -> Path:
    return repo_root / "src" / "dashboard_routes"


def _route_modules(repo_root: Path) -> list[Path]:
    return sorted(_routes_dir(repo_root).glob("*.py"))


def test_route_modules_import_shared_symbols_via_canonical_path(
    real_repo_root: Path,
) -> None:
    """No route module may bind ``RouteContext``/``register`` from bare ``_routes``."""
    offenders: list[str] = []
    for path in _route_modules(real_repo_root):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # ``from _routes import RouteContext`` — absolute (level 0), bare module.
            if isinstance(node, ast.ImportFrom):
                binds_guarded = any(a.name in _GUARDED_NAMES for a in node.names)
                if binds_guarded and node.level == 0 and node.module in _BARE_MODULES:
                    offenders.append(
                        f"{path.name}:{node.lineno} — `from {node.module} import "
                        f"{', '.join(a.name for a in node.names)}` uses the bare "
                        "`_routes` spelling; use `dashboard_routes._routes` "
                        "(absolute) or `._routes` (relative)."
                    )
            # ``import _routes`` — bare top-level import of the module itself.
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in _BARE_MODULES:
                        offenders.append(
                            f"{path.name}:{node.lineno} — `import {alias.name}` uses "
                            "the bare `_routes` spelling (dual module identity); "
                            "import from `dashboard_routes._routes`."
                        )

    assert not offenders, (
        "dashboard route module(s) import a shared route symbol via the bare "
        "`_routes` spelling, which creates a second module object with a distinct "
        "`RouteContext` identity (#10979 / #10874 dual-import-identity trap):\n  "
        + "\n  ".join(offenders)
    )


def test_guard_covers_the_live_route_modules(real_repo_root: Path) -> None:
    """Sanity: the guard is actually scanning the decomposed route package.

    Without this, a rename of the package would silently make the guard vacuous.
    """
    modules = {p.name for p in _route_modules(real_repo_root)}
    assert "_routes.py" in modules, (
        "dashboard_routes/_routes.py not found — guard vacuous"
    )
    # At least the canonical consumers the ADR-0030 decomposition produced.
    assert len(modules) >= 5, f"expected the decomposed route package, saw {modules}"
