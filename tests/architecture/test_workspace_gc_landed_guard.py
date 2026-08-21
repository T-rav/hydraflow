"""Architecture pin: every WorkspaceGC destroy path shares one landed predicate."""

from __future__ import annotations

import ast
from pathlib import Path

_SOURCE = Path(__file__).resolve().parents[2] / "src" / "workspace_gc_loop.py"
_PREDICATE = "_worktree_work_has_landed"


def _method_calls() -> dict[str, list[str]]:
    tree = ast.parse(_SOURCE.read_text())
    calls: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        names = [
            child.func.attr
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
        ]
        calls[node.name] = names
    return calls


def test_all_workspace_destroy_decisions_share_exact_head_landed_predicate() -> None:
    calls = _method_calls()
    direct_destroy_callers = {
        method for method, names in calls.items() if "destroy" in names
    }
    guarded_callers = {method for method, names in calls.items() if _PREDICATE in names}

    assert (direct_destroy_callers, guarded_callers) == (
        {"_do_work", "_collect_orphaned_dirs"},
        {"_do_work", "_collect_orphaned_dirs", "_reap_worktree_if_safe"},
    )


def test_every_landed_predicate_call_coordinates_issue_identity() -> None:
    tree = ast.parse(_SOURCE.read_text())
    predicate_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == _PREDICATE
    ]

    assert predicate_calls
    assert all(
        any(keyword.arg == "expected_issue" for keyword in call.keywords)
        for call in predicate_calls
    )
