"""Structural gate: ``._run_gh(...)``/``._repo`` only reachable via ``self``.

#11418 (the "structural root" of a six-issue #11292 class): ``StaleIssueLoop``,
``ReportIssueLoop``, and ``service_registry.py`` called
``self._prs._run_gh(...)`` / ``self._prs._repo`` directly — reaching around
``PRPort`` to a private ``PRManager`` implementation detail. A call that never
crosses the Port can never be modelled by ``FakeGitHub`` (#11413's fake gap
could only exist because of this), and the existing fake-conformance test
(``test_mockworld_fakes_conformance.py``) only walks methods *declared on
PRPort* — it structurally cannot see a bypass that never touches the Port at
all (#11415).

This gate makes that reach-around class structurally impossible to
reintroduce: ``PRManager``'s own methods (and its promotion mixin) legitimately
call ``self._run_gh(...)`` / read ``self._repo`` — that's *within* the
adapter. Any OTHER receiver (``self._prs._run_gh``, ``self._pr_manager._repo``,
``prs._run_gh``, a bare collaborator variable, ...) is exactly the bypass
class #11418 fixed. Add a real ``PRPort`` method instead (see
``PRManager.list_branch_refs`` / ``list_branch_commits`` / ``get_issue_body``
/ ``list_all_issues_for_fitness`` / ``list_all_prs_for_fitness`` for the
promoted precedent) so FakeGitHub can model the call by construction.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent.parent / "src"

_ATTRS = {"_run_gh", "_repo"}


def _is_bare_self(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "self"


def _reach_around_accesses(tree: ast.AST) -> list[tuple[str, int]]:
    """Return (attr, lineno) for every ``X.attr`` where ``attr`` is
    ``_run_gh``/``_repo`` and ``X`` is not a bare ``self``."""
    offenders: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if node.attr not in _ATTRS:
            continue
        if _is_bare_self(node.value):
            continue
        offenders.append((node.attr, node.lineno))
    return offenders


def test_no_run_gh_or_repo_reach_around_outside_self() -> None:
    """``._run_gh``/``._repo`` must only ever be accessed as ``self.<attr>``.

    PRManager and PRManagerPromotionMixin read/call these on themselves
    (``self._run_gh(...)``, ``self._repo``) — that's the adapter's own
    implementation, not a bypass. Any access through a collaborator
    reference (``self._prs.X``, ``prs.X``, ``self._pr_manager.X``, ...) is
    the #11418 reach-around class: promote a real PRPort method instead.
    """
    offenders: list[str] = []
    for py in sorted(SRC.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for attr, lineno in _reach_around_accesses(tree):
            offenders.append(f"{py.relative_to(SRC)}:{lineno} .{attr}")
    assert not offenders, (
        f"Found ._run_gh/._repo accessed through something other than a "
        f"bare `self`: {offenders}. This is the #11418 PRPort reach-around "
        "class — add a real PRPort method (ports.py + pr_manager.py + "
        "FakeGitHub) instead of composing PRManager's private _run_gh/_repo "
        "seam from outside the adapter."
    )


def test_the_guard_still_catches_a_synthetic_reach_around() -> None:
    """Guard the guard: an empty offender list must not be vacuous."""
    tree = ast.parse("self._prs._run_gh('gh', 'issue', 'list')\nx = self._prs._repo\n")
    offenders = _reach_around_accesses(tree)
    assert {(attr, ln) for attr, ln in offenders} == {("_run_gh", 1), ("_repo", 2)}


def test_self_run_gh_and_repo_are_not_flagged() -> None:
    """The legitimate in-adapter shape must never false-positive."""
    tree = ast.parse("self._run_gh('gh', 'issue', 'list')\nx = self._repo\n")
    assert _reach_around_accesses(tree) == []
