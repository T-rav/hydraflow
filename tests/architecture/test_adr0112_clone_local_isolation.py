"""ADR-0112 enforcement: per-issue isolation is a ``git clone --local``.

ADR-0112 (Per-Issue Isolation via Local Git Clone) supersedes ADR-0003's
``git worktree add`` mechanism. ``WorkspaceManager`` now creates an
*independent* local clone per issue — ``git clone --local --no-checkout`` of
the primary checkout — at a repo-slug-scoped workspace path, rather than a
linked git worktree that shares the primary repo's ``.git``. The ``wt_path`` /
"worktree" identifiers left in ``src/workspace/_manager.py`` are vestigial names for
what are now full local clones (hardlinked objects, own ``.git/``).

Like ADR-0107, this is a mechanism decision with a crisp, machine-checkable
surface, so it earns a REAL asserting check. These tests read the on-disk
source (AST) so the isolation mechanism cannot silently drift back to
``git worktree add`` — or drop ``--local`` and lose object hardlinking /
independence — without turning this check red.
"""

from __future__ import annotations

import ast
from pathlib import Path


def _function_node(
    tree: ast.AST, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == name
        ):
            return node
    return None


def _string_args(call: ast.Call) -> list[str]:
    """String literal positional args of a call (the argv of a subprocess run)."""
    return [
        a.value
        for a in call.args
        if isinstance(a, ast.Constant) and isinstance(a.value, str)
    ]


def _create_path_argvs(real_repo_root: Path) -> list[list[str]]:
    """String-arg lists of every call inside WorkspaceManager._create_unlocked."""
    tree = ast.parse((real_repo_root / "src" / "workspace" / "_manager.py").read_text())
    node = _function_node(tree, "_create_unlocked")
    assert node is not None, (
        "WorkspaceManager._create_unlocked not found in src/workspace/_manager.py — the "
        "per-issue workspace creation seam ADR-0112 governs is missing/renamed"
    )
    return [_string_args(c) for c in ast.walk(node) if isinstance(c, ast.Call)]


def test_workspace_create_uses_git_clone_local(real_repo_root: Path) -> None:
    """ADR-0112: the per-issue workspace is created with ``git clone --local
    --no-checkout`` of the primary checkout — an independent clone with
    hardlinked objects, not a linked git worktree."""
    argvs = _create_path_argvs(real_repo_root)
    clone_argvs = [args for args in argvs if "clone" in args]
    assert clone_argvs, (
        "WorkspaceManager._create_unlocked must invoke `git clone` to create "
        "the per-issue workspace (ADR-0112)"
    )
    assert any("--local" in args for args in clone_argvs), (
        "the per-issue clone must pass `--local` (hardlinked objects, own "
        "independent .git/) — ADR-0112"
    )
    assert any("--no-checkout" in args for args in clone_argvs), (
        "the per-issue clone must pass `--no-checkout` (the branch is checked "
        "out explicitly afterward) — ADR-0112"
    )


def test_workspace_isolation_is_not_a_git_worktree_add(real_repo_root: Path) -> None:
    """ADR-0112 (supersedes ADR-0003): the isolation mechanism moved OFF
    ``git worktree add``. The create path must not spawn a linked worktree —
    the ``wt_path`` / "worktree" names remaining in the module are vestigial."""
    for args in _create_path_argvs(real_repo_root):
        assert not ("worktree" in args and "add" in args), (
            "WorkspaceManager._create_unlocked must not use `git worktree add` "
            "for isolation — ADR-0112 replaced it with `git clone --local`"
        )


def test_workspace_path_is_repo_slug_scoped(real_repo_root: Path) -> None:
    """ADR-0112: the workspace lives at a repo-slug-scoped isolated path,
    resolved via ``HydraFlowConfig.workspace_path_for_issue`` — distinct from
    the primary checkout so per-issue clones cannot collide across repos."""
    tree = ast.parse((real_repo_root / "src" / "workspace" / "_manager.py").read_text())
    node = _function_node(tree, "_create_unlocked")
    assert node is not None
    attrs = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
    assert "workspace_path_for_issue" in attrs, (
        "the workspace path must come from config.workspace_path_for_issue "
        "(repo-slug-scoped) — ADR-0112"
    )

    cfg = ast.parse((real_repo_root / "src" / "config.py").read_text())
    method: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for cls in cfg.body:
        if isinstance(cls, ast.ClassDef) and cls.name == "HydraFlowConfig":
            for m in cls.body:
                if (
                    isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef)
                    and m.name == "workspace_path_for_issue"
                ):
                    method = m
    assert method is not None, (
        "HydraFlowConfig.workspace_path_for_issue not found in src/config.py"
    )
    cfg_attrs = {n.attr for n in ast.walk(method) if isinstance(n, ast.Attribute)}
    assert "repo_slug" in cfg_attrs, (
        "workspace_path_for_issue must scope the path by repo_slug so per-issue "
        "clones are isolated per repository — ADR-0112"
    )
