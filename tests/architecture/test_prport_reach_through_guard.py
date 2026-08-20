"""Structural gate: no cross-module ``._run_gh(``/``._repo`` reach-through.

``_run_gh`` and ``_repo`` are private implementation details of
``pr_manager.PRManager`` (and its ``pr_manager_promotion`` mixin) and the
``FakeGitHub`` test double. Reaching through a ``PRPort``-typed collaborator
to call ``self._prs._run_gh(...)`` or read ``self._prs._repo`` bypasses the
hexagonal ``PRPort`` boundary: the read becomes a raw ``gh api`` string
FakeGitHub's generic dispatcher must string-match rather than a Protocol
method the fake's coverage is checked against (#11418). Four such
reach-throughs — two in ``StaleIssueLoop``'s branch-GC, one each in
``ReportIssueLoop._verify_issue`` and ``service_registry``'s fitness
fetcher — were promoted to first-class ``PRPort`` methods
(``list_branch_refs``, ``list_branch_commits``, ``get_issue_body``,
``list_all_issues``, ``list_all_prs``); this gate keeps the category
retired rather than letting a new call site quietly reintroduce it.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent.parent / "src"

#: Files that legitimately own ``_run_gh``/``_repo`` as real attributes:
#: PRManager defines and uses them directly (``self._run_gh``/``self._repo``
#: are bare-``self`` accesses, never flagged below regardless of allowlist);
#: its promotion mixin shares the same ``self``; FakeGitHub implements its
#: own ``_run_gh`` dispatcher method. Reserved for genuine owners only — do
#: NOT add a file here to silence a real reach-through.
_ALLOWED = {"pr_manager.py", "pr_manager_promotion.py", "fake_github.py"}

_GUARDED_ATTRS = {"_run_gh", "_repo"}


def _reach_through_sites(tree: ast.AST) -> list[tuple[int, str]]:
    """Return ``(lineno, attr)`` for every non-``self`` access to a guarded attr.

    ``self._run_gh(...)`` / ``self._repo`` (bare ``self`` as the immediate
    object) are the legitimate in-class case and are not flagged. Anything
    else — ``self._prs._run_gh``, ``self._pr_manager._repo``,
    ``prs._run_gh``, a chained ``self._x._y._repo``, etc. — reaches through
    a collaborator's private attribute and is flagged.
    """
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr not in _GUARDED_ATTRS:
            continue
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            continue
        offenders.append((node.lineno, node.attr))
    return offenders


def test_no_cross_module_run_gh_or_repo_reach_through() -> None:
    offenders: list[str] = []
    for py in sorted(SRC.rglob("*.py")):
        if py.name in _ALLOWED:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for lineno, attr in _reach_through_sites(tree):
            offenders.append(f"{py.relative_to(SRC)}:{lineno} (.{attr})")
    assert not offenders, (
        f"Cross-module ._run_gh(/._repo reach-through outside {sorted(_ALLOWED)}: "
        f"{offenders}. Add a PRPort method (pr_manager.py + ports.py + "
        "FakeGitHub) and call that instead of reaching through a PRPort-"
        "typed collaborator's private attributes — see #11418."
    )


def test_the_allowlisted_files_still_use_the_guarded_attrs() -> None:
    """Guard the guard: an empty/stale allowlist entry must not silently pass."""
    for name in _ALLOWED:
        matches = list(SRC.rglob(name))
        assert matches, f"Allowlisted file {name!r} no longer exists under src/"
        for path in matches:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            found_attrs = {
                node.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute) and node.attr in _GUARDED_ATTRS
            }
            assert found_attrs, (
                f"{name} is allowlisted but no longer references "
                f"{sorted(_GUARDED_ATTRS)} — remove it from _ALLOWED"
            )
