"""Architecture pin: every WorkspaceGC destroy AND branch-delete path shares one landed proof."""

from __future__ import annotations

import ast
from pathlib import Path

_SOURCE = Path(__file__).resolve().parents[2] / "src" / "workspace_gc_loop.py"
_PREDICATE = "_worktree_work_has_landed"
_BRANCH_PREDICATE = "_branch_work_has_landed"
_DRIVER = "_drive_landed_proof"
_FORCE_DELETE = ("git", "branch", "-D")


def _functions() -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(_SOURCE.read_text())
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _callee_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return None


def _method_calls() -> dict[str, list[str]]:
    """Callee names (method or bare function) invoked inside each function."""
    calls: dict[str, list[str]] = {}
    for name, node in _functions().items():
        calls[name] = [
            callee
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
            and (callee := _callee_name(child)) is not None
        ]
    return calls


def _subprocess_prefixes(node: ast.AST) -> list[tuple[str, ...]]:
    """Leading constant positional args of every ``run_subprocess`` call in *node*."""
    prefixes: list[tuple[str, ...]] = []
    for child in ast.walk(node):
        if not (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "run_subprocess"
        ):
            continue
        constants: list[str] = []
        for arg in child.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                constants.append(arg.value)
            else:
                break
        prefixes.append(tuple(constants))
    return prefixes


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


def _attribute_call_linenos(node: ast.AST, attr: str) -> list[int]:
    return [
        child.lineno
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == attr
    ]


def _force_delete_linenos(node: ast.AST) -> list[int]:
    return [
        child.lineno
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id == "run_subprocess"
        and tuple(arg.value for arg in child.args[:3] if isinstance(arg, ast.Constant))
        == _FORCE_DELETE
    ]


def test_every_branch_force_delete_is_post_proof() -> None:
    """#11571: a branch force-delete only runs after the branch-tip proof
    (phase 3) or after the worktree proof authorized a reap (``_reap_worktree``,
    which only ``_reap_worktree_if_safe`` may call). "After" is pinned on
    source order inside phase 3, not on mere co-presence."""
    functions = _functions()
    calls = _method_calls()
    force_delete_sites = {
        name for name, node in functions.items() if _force_delete_linenos(node)
    }
    reap_callers = {
        method for method, names in calls.items() if "_reap_worktree" in names
    }
    phase3 = functions["_collect_orphaned_branches"]
    proof_linenos = _attribute_call_linenos(phase3, _BRANCH_PREDICATE)
    delete_linenos = _force_delete_linenos(phase3)

    assert force_delete_sites == {"_collect_orphaned_branches", "_reap_worktree"}
    assert (len(proof_linenos), len(delete_linenos)) == (1, 1)
    assert proof_linenos[0] < delete_linenos[0]
    assert reap_callers == {"_reap_worktree_if_safe"}
    assert _PREDICATE in calls["_reap_worktree_if_safe"]


def test_both_landed_predicates_share_one_driver_and_one_subprocess_seam() -> None:
    """One ladder, one module-level driver: neither front-end spawns git itself."""
    functions = _functions()
    calls = _method_calls()

    assert (_DRIVER in calls[_PREDICATE], _DRIVER in calls[_BRANCH_PREDICATE]) == (
        True,
        True,
    )
    assert (
        _subprocess_prefixes(functions[_PREDICATE]),
        _subprocess_prefixes(functions[_BRANCH_PREDICATE]),
        len(_subprocess_prefixes(functions[_DRIVER])),
    ) == ([], [], 1)
