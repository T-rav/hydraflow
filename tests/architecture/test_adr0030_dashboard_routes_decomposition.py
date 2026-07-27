"""ADR-0030 enforcement: dashboard routes domain-decomposition pattern.

ADR-0030 (Dashboard Routes Domain Decomposition) decides that route handlers
are split out of the monolithic ``_routes.py`` into domain-specific files, each
exporting a ``register(router: APIRouter, ctx: RouteContext) -> None`` function
that decorates the shared router directly (chosen over ``include_router`` so URL
paths and the 381 existing dashboard tests are unchanged). ``_routes.py``
retains the ``RouteContext`` dataclass and the ``create_router()`` coordinator.

The pattern is a concretely testable structural invariant: the domain-route
modules the ADR enumerates each export the ``register(router, ctx)`` seam, the
``create_router()`` coordinator actually wires those ``register`` calls, and the
coordinator + ``RouteContext`` survive in ``_routes.py``. These asserting tests
read the on-disk tree via AST (no imports), so the decision cannot silently
drift — e.g. an enumerated domain dropping ``register``, the coordinator no
longer invoking it, or ``create_router`` being renamed away. (Some *later*
domains legitimately use a prefix-mounted ``build_<domain>_router`` +
``include_router`` pattern for fresh ``/api/...`` prefixes with no existing
tests to break, so the ``register`` seam is asserted for the ADR-decided
domains, not blindly for every ``_*_routes.py`` file.)
"""

from __future__ import annotations

import ast
from pathlib import Path

# Domain route modules the ADR enumerates that survive today (the ADR notes
# `_crates_routes.py` was retired in #10512). Each must export `register`.
_ADR_NAMED_DOMAINS = (
    "_epic_routes.py",
    "_hitl_routes.py",
    "_control_routes.py",
    "_metrics_routes.py",
    "_reports_routes.py",
    "_state_routes.py",
)


def _module_functions(path: Path) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        n.name: n
        for n in tree.body
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _routes_dir(repo_root: Path) -> Path:
    return repo_root / "src" / "dashboard_routes"


def _register_param_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    return [a.arg for a in fn.args.args]


def test_adr_named_domains_export_register_with_ctx_signature(
    real_repo_root: Path,
) -> None:
    """ADR-0030: the enumerated domain modules each export a module-level
    ``register(router, ctx)`` seam with the decided signature."""
    routes_dir = _routes_dir(real_repo_root)
    missing: list[str] = []
    bad_sig: list[str] = []
    for name in _ADR_NAMED_DOMAINS:
        fns = _module_functions(routes_dir / name)
        register = fns.get("register")
        if register is None:
            missing.append(name)
            continue
        params = _register_param_names(register)
        if params[:2] != ["router", "ctx"]:
            bad_sig.append(f"{name}::register{tuple(params)}")

    assert not missing, (
        "ADR-0030 enumerated domain modules must export register(router, ctx); "
        f"missing in: {missing}"
    )
    assert not bad_sig, (
        "ADR-0030 register() must take (router, ctx) as its first two "
        f"parameters; wrong signature in: {bad_sig}"
    )


def _create_router_node(routes_py: Path) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(routes_py.read_text(encoding="utf-8"))
    for n in tree.body:
        if (
            isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
            and n.name == "create_router"
        ):
            return n
    raise AssertionError("create_router coordinator not found in _routes.py")


def test_create_router_wires_each_named_domain_register(real_repo_root: Path) -> None:
    """ADR-0030: the ``create_router()`` coordinator imports ``register`` from
    each enumerated domain module and calls it — proving the domains are wired
    through the ``register(router, ctx)`` seam, not orphaned."""
    create_router = _create_router_node(_routes_dir(real_repo_root) / "_routes.py")

    # Map each enumerated domain stem -> the local alias `register` is bound to.
    stems = {name[: -len(".py")] for name in _ADR_NAMED_DOMAINS}
    alias_for_stem: dict[str, str] = {}
    for node in ast.walk(create_router):
        if isinstance(node, ast.ImportFrom) and node.module:
            stem = node.module.rsplit(".", 1)[-1]
            if stem in stems:
                for alias in node.names:
                    if alias.name == "register":
                        alias_for_stem[stem] = alias.asname or "register"

    not_imported = sorted(stems - set(alias_for_stem))
    assert not not_imported, (
        "create_router() must import register from each ADR-0030 domain module; "
        f"no `register` import for: {not_imported}"
    )

    called = {
        node.func.id
        for node in ast.walk(create_router)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    not_called = sorted(
        stem for stem, alias in alias_for_stem.items() if alias not in called
    )
    assert not not_called, (
        "create_router() must invoke each domain's register(); not called for: "
        f"{not_called}"
    )


def test_routes_py_retains_coordinator_and_context(real_repo_root: Path) -> None:
    """ADR-0030: ``_routes.py`` keeps the ``RouteContext`` dataclass and the
    ``create_router()`` coordinator that wires the domain ``register`` calls."""
    tree = ast.parse((_routes_dir(real_repo_root) / "_routes.py").read_text())
    classes = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    funcs = {
        n.name
        for n in tree.body
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assert "RouteContext" in classes, (
        "_routes.py must define the RouteContext dataclass"
    )
    assert "create_router" in funcs, (
        "_routes.py must define the create_router() coordinator"
    )
