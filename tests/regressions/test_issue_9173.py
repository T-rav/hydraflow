"""Regression reproduction for issue #9173 — ADR-0009 cited-module drift.

Issue #9173 is an `adr_touchpoint_auditor` rollup: modules cited by
**ADR-0009 (Multi-Repo Process-Per-Repo Model, status: Accepted)** drifted
across 10 merged PRs without the ADR being updated. The auditor fires on a
file-level signal (cited `src/` file touched, ADR file absent from the diff),
so it cannot tell whether the ADR's *content* is still accurate.

This test reproduces the underlying drift concretely: it parses ADR-0009 with
the project's own citation parser (``adr_index.parse_adr_file`` — the same
regex/index the auditor and the P2 CI gate use) and asserts every
``src/<file>.py:<Symbol>`` anchor still resolves to live code via AST.

It is RED today because ADR-0009 cites code that has since been renamed or
deleted:

  * ``src/config.py:HydraFlowConfig.worktree_path_for_issue`` — the method was
    renamed to ``workspace_path_for_issue`` (worktree→workspace refactor).
  * ``src/worktree.py:WorktreeManager`` — ``src/worktree.py`` no longer exists;
    the type is now ``WorkspaceManager`` in ``src/workspace.py``.
  * ``src/hf_cli/supervisor_service.py:_start_repo`` / ``:RUNNERS`` — that
    supervisor module file no longer exists under that path.

The test goes GREEN once ADR-0009 is updated to cite the current symbols
(repair option 1 in the issue) — i.e. it tracks resolution of the actual
drift, not the auditor's coarse touch signal.

NOTE: this is a *reproduction*, not a fix. Do not edit ``src/`` to make it
pass — the ADR markdown is what is stale.
"""

from __future__ import annotations

import ast
from pathlib import Path

from adr_index import parse_adr_file

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ADR_GLOB = "0009-*.md"


def _find_adr_0009() -> Path:
    matches = sorted((_REPO_ROOT / "docs" / "adr").glob(_ADR_GLOB))
    assert matches, "ADR-0009 markdown file not found under docs/adr/"
    return matches[0]


def _module_defines(tree: ast.Module, dotted: str) -> bool:
    """True iff *dotted* (e.g. ``Class.method`` or ``func`` or ``NAME``) is
    defined at the corresponding nesting level in *tree*."""
    parts = dotted.split(".")

    def names_in(body: list[ast.stmt]) -> set[str]:
        found: set[str] = set()
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found.add(node.name)
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        found.add(tgt.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                found.add(node.target.id)
        return found

    body: list[ast.stmt] = list(tree.body)
    for i, part in enumerate(parts):
        if part not in names_in(body):
            return False
        if i == len(parts) - 1:
            return True
        # Descend into the named class to resolve the next path component.
        nxt = next(
            (n for n in body if isinstance(n, ast.ClassDef) and n.name == part),
            None,
        )
        if nxt is None:
            return False
        body = list(nxt.body)
    return True


def test_issue_9173_adr_0009_citations_resolve_to_live_code() -> None:
    """Every ``src/...py:Symbol`` anchor in ADR-0009 must resolve in live code.

    RED for issue #9173: ADR-0009 cites renamed/deleted symbols and files.
    """
    adr = parse_adr_file(_find_adr_0009())

    missing_files: list[str] = []
    missing_symbols: list[str] = []

    for cited_file, symbols in sorted(adr.source_symbols.items()):
        abs_path = _REPO_ROOT / cited_file
        if not abs_path.is_file():
            missing_files.append(cited_file)
            continue
        if not symbols:
            continue  # bare file citation, nothing to resolve at symbol level
        tree = ast.parse(abs_path.read_text())
        for symbol in sorted(symbols):
            if not _module_defines(tree, symbol):
                missing_symbols.append(f"{cited_file}:{symbol}")

    violations = [f"missing file: {f}" for f in missing_files] + [
        f"missing symbol: {s}" for s in missing_symbols
    ]
    assert not violations, (
        "ADR-0009 cites code that no longer exists (drift, issue #9173):\n  "
        + "\n  ".join(violations)
    )
