"""Regression test for issue #6812.

Bug: ``ServiceRegistry`` is a plain dataclass with no ``aclose()`` lifecycle
method. ``build_services()`` creates a ``HindsightClient`` (wrapping an
``httpx.AsyncClient``) and stores it on the registry, but nothing ever closes
it. The registry is the composition root — it owns the client's lifetime —
yet has no shutdown hook to drain the connection pool.

The tests use AST inspection to verify:
1. ``ServiceRegistry`` exposes an ``aclose()`` async method.
2. That method contains a call to close the ``hindsight`` client.

Both are RED against the current buggy code and will turn GREEN once the
lifecycle method is added.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

SERVICE_REGISTRY_PY = SRC_DIR / "service_registry.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_class_node(source: str, class_name: str) -> ast.ClassDef:
    """Return the AST ``ClassDef`` node for *class_name*."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    pytest.fail(f"{class_name!r} not found in service_registry.py")


def _find_async_method(
    cls_node: ast.ClassDef, method_name: str
) -> ast.AsyncFunctionDef | None:
    """Return the ``AsyncFunctionDef`` for *method_name* within *cls_node*."""
    for item in cls_node.body:
        if isinstance(item, ast.AsyncFunctionDef) and item.name == method_name:
            return item
    return None


def _body_contains_attr_call(
    stmts: list[ast.stmt], obj_attr_pairs: list[tuple[str, str]]
) -> bool:
    """Check whether *stmts* contain ``await <obj>.<attr>()`` for any pair."""
    for node in ast.walk(ast.Module(body=stmts, type_ignores=[])):
        if not isinstance(node, ast.Await):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if not isinstance(func, ast.Attribute):
            continue
        # Handle self.hindsight.close() — func.value is self.hindsight
        if isinstance(func.value, ast.Attribute):
            outer = func.value
            for obj, attr in obj_attr_pairs:
                if outer.attr == obj and func.attr == attr:
                    return True
        # Handle hindsight.close() — func.value is a Name
        if isinstance(func.value, ast.Name):
            for obj, attr in obj_attr_pairs:
                if func.value.id == obj and func.attr == attr:
                    return True
    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestServiceRegistryLifecycle:
    """ServiceRegistry must expose an async shutdown method."""

    @pytest.mark.xfail(reason="Regression for issue #6812 — fix not yet landed", strict=False)
    def test_service_registry_has_aclose_method(self) -> None:
        """ServiceRegistry must define an ``aclose()`` async method so
        callers (e.g. the orchestrator) can cleanly shut down owned
        resources like the HindsightClient's httpx connection pool.

        BUG (current): ServiceRegistry is a bare dataclass with no
        lifecycle methods — the HindsightClient is created in
        build_services() (line ~240) but nothing can close it.
        """
        source = SERVICE_REGISTRY_PY.read_text()
        cls = _get_class_node(source, "ServiceRegistry")
        method = _find_async_method(cls, "aclose")

        assert method is not None, (
            "BUG #6812: ServiceRegistry has no aclose() async method. "
            "The HindsightClient (httpx.AsyncClient) created by "
            "build_services() is never closed, leaking the connection "
            "pool on every shutdown."
        )

    def test_aclose_closes_hindsight_client(self) -> None:
        """Once ``aclose()`` exists, it must call ``self.hindsight.close()``
        or ``self.hindsight.aclose()`` to drain the httpx pool.

        This test is SKIPPED (not failed) if ``aclose()`` doesn't exist
        yet — ``test_service_registry_has_aclose_method`` already covers
        that gap.
        """
        source = SERVICE_REGISTRY_PY.read_text()
        cls = _get_class_node(source, "ServiceRegistry")
        method = _find_async_method(cls, "aclose")

        if method is None:
            pytest.skip(
                "aclose() not yet defined — see test_service_registry_has_aclose_method"
            )

        closes_client = _body_contains_attr_call(
            method.body,
            [("hindsight", "close"), ("hindsight", "aclose")],
        )
        assert closes_client, (
            "BUG #6812: ServiceRegistry.aclose() exists but does not call "
            "self.hindsight.close() or self.hindsight.aclose(). The "
            "HindsightClient connection pool still leaks."
        )

    def test_hindsight_field_exists_but_no_cleanup(self) -> None:
        """Prove the asymmetry: ServiceRegistry declares a ``hindsight``
        field (the client IS stored) but has zero lifecycle methods to
        shut it down.
        """
        source = SERVICE_REGISTRY_PY.read_text()
        cls = _get_class_node(source, "ServiceRegistry")

        # The class DOES have a hindsight field.
        has_hindsight_field = any(
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.target.id == "hindsight"
            for stmt in cls.body
        )
        assert has_hindsight_field, (
            "Expected ServiceRegistry to have a 'hindsight' field"
        )

        # But it has NO async methods at all — no lifecycle management.
        async_methods = [
            item.name for item in cls.body if isinstance(item, ast.AsyncFunctionDef)
        ]
        assert not async_methods, (
            f"ServiceRegistry now has async methods {async_methods} — "
            "if aclose() was added, update test_aclose_closes_hindsight_client "
            "and remove this asymmetry test."
        )
