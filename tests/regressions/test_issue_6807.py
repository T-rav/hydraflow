"""Regression test for issue #6807.

Bug: ``server._run_with_dashboard()`` constructs a ``HindsightClient``
(which wraps ``httpx.AsyncClient``) at line ~232 but the ``finally`` block
only stops the orchestrator and dashboard — it never calls
``hindsight_client.close()``.  This leaks an httpx connection pool on
every dashboard-mode shutdown.

The test inspects the AST of ``_run_with_dashboard`` and asserts that its
``finally`` block contains a call to ``hindsight_client.close()``.  This is
RED against the current buggy code and will turn GREEN once the cleanup
call is added.
"""

from __future__ import annotations

import ast
import sys
import textwrap
from pathlib import Path

import pytest

# Ensure src/ is importable for source inspection.
SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

SERVER_PY = SRC_DIR / "server.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_function_node(source: str, func_name: str) -> ast.AsyncFunctionDef:
    """Return the AST node for *func_name* from *source*."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == func_name:
            return node
    pytest.fail(f"{func_name!r} not found in server.py")


def _finally_body(func: ast.AsyncFunctionDef) -> list[ast.stmt]:
    """Return the statements in the first ``try/finally`` of *func*."""
    for node in ast.walk(func):
        if isinstance(node, ast.Try) and node.finalbody:
            return node.finalbody
    return []


def _dump_stmts(stmts: list[ast.stmt]) -> str:
    """Human-readable dump of statement list (for diagnostics)."""
    return textwrap.indent(
        ast.dump(ast.Module(body=stmts, type_ignores=[]), indent=2), "  "
    )


def _contains_close_call(stmts: list[ast.stmt], var_name: str) -> bool:
    """Check whether *stmts* contain ``await <var_name>.close()``."""
    for node in ast.walk(ast.Module(body=stmts, type_ignores=[])):
        if not isinstance(node, ast.Await):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "close"
            and isinstance(func.value, ast.Name)
            and func.value.id == var_name
        ):
            return True
    return False


def _contains_aclose_call(stmts: list[ast.stmt], var_name: str) -> bool:
    """Check whether *stmts* contain ``await <var_name>.aclose()``."""
    for node in ast.walk(ast.Module(body=stmts, type_ignores=[])):
        if not isinstance(node, ast.Await):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "aclose"
            and isinstance(func.value, ast.Name)
            and func.value.id == var_name
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHindsightClientCleanup:
    """_run_with_dashboard must close the HindsightClient on shutdown."""

    @pytest.mark.xfail(reason="Regression for issue #6807 — fix not yet landed", strict=False)
    def test_finally_block_closes_hindsight_client(self) -> None:
        """The finally block must call ``hindsight_client.close()`` or
        ``hindsight_client.aclose()`` so the httpx connection pool is
        properly drained on SIGTERM/SIGINT.

        BUG (current): the finally block at server.py:265-268 only stops
        the orchestrator and dashboard — hindsight_client is never closed.
        """
        source = SERVER_PY.read_text()
        func = _get_function_node(source, "_run_with_dashboard")
        finally_stmts = _finally_body(func)

        assert finally_stmts, (
            "_run_with_dashboard has no finally block — "
            "nothing is cleaned up on shutdown"
        )

        has_close = _contains_close_call(finally_stmts, "hindsight_client")
        has_aclose = _contains_aclose_call(finally_stmts, "hindsight_client")

        assert has_close or has_aclose, (
            "BUG #6807: _run_with_dashboard finally block does not call "
            "hindsight_client.close() or hindsight_client.aclose(). "
            "The httpx.AsyncClient connection pool leaks on every "
            "dashboard-mode shutdown.\n\n"
            f"Current finally block AST:\n{_dump_stmts(finally_stmts)}"
        )

    def test_hindsight_client_created_but_not_in_finally(self) -> None:
        """Verify the gap: hindsight_client IS created in the function body
        but is NOT referenced in the finally block at all.

        This test proves the asymmetry — the client is constructed but
        never cleaned up.
        """
        source = SERVER_PY.read_text()
        func = _get_function_node(source, "_run_with_dashboard")
        func_source = ast.get_source_segment(source, func)
        assert func_source is not None

        # The function DOES create a HindsightClient.
        assert "HindsightClient(" in func_source, (
            "Expected _run_with_dashboard to construct a HindsightClient"
        )

        # But the finally block does NOT reference it at all.
        finally_stmts = _finally_body(func)
        finally_source = "\n".join(
            ast.get_source_segment(source, stmt) or "" for stmt in finally_stmts
        )

        assert "hindsight_client" not in finally_source, (
            "If hindsight_client IS referenced in the finally block, "
            "then the bug may already be fixed — update this test."
        )
