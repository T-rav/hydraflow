"""Unit tests for the shared read-only git timeout constant (#10402)."""

from __future__ import annotations

import ast
import inspect

import git_timeouts


def test_git_readonly_timeout_s_value() -> None:
    assert git_timeouts.GIT_READONLY_TIMEOUT_S == 60


def test_git_readonly_timeout_s_is_int() -> None:
    assert isinstance(git_timeouts.GIT_READONLY_TIMEOUT_S, int)


def test_git_timeouts_module_is_leaf() -> None:
    """``git_timeouts`` must import nothing from the src tree — it's the
    shared home for the read-only git timeout tier, imported by seven other
    modules; a back-import would risk a circular import for any of them."""
    tree = ast.parse(inspect.getsource(git_timeouts))
    non_future_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and not (isinstance(node, ast.ImportFrom) and node.module == "__future__")
    ]
    assert not non_future_imports, (
        "git_timeouts.py must stay a zero-dependency leaf module — found "
        f"imports: {[ast.dump(n) for n in non_future_imports]}"
    )
