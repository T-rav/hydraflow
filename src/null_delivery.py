"""Null-delivery detection for implementation results.

A *null delivery* is a branch whose diff is non-empty yet contains **only**
non-deliverable artifacts — planner LikeC4 context diagrams and auto-generated
knowledge files — and no actual code, tests, or assets.

Background (issue #9480): the planner copies ``.likec4`` context diagrams into
the implementer's worktree (``ImplementPhase`` →
``PlannerRunner.copy_diagrams_to_workspace``) so the agent has architectural
context on disk. When an implement agent produces no real code, the auto-commit
fallback (``agent.py`` ``_force_commit_uncommitted``) salvages only those
injected diagrams. The result is a PR that claims ``Closes #N`` for a code issue
but ships nothing — and the ``commits == 0`` zero-commit guard does not catch it
because the salvage created a commit. This module supplies the path-level
classifier that lets the pipeline recognise and reject that outcome.

The classifier is intentionally pure (no I/O) so it is exhaustively unit
testable; the git plumbing that produces the changed-file list lives in the
caller.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

# Directory prefixes whose contents are auto-generated knowledge artifacts —
# never a standalone deliverable for a code issue.
_NON_DELIVERABLE_PREFIXES: tuple[str, ...] = (
    "repo_wiki/",  # per-repo wiki ingest (RepoWikiLoop)
    "docs/arch/generated/",  # auto-regenerated arch artifacts (arch.runner)
)

# Exact paths that are auto-generated metadata.
_NON_DELIVERABLE_EXACT: frozenset[str] = frozenset(
    {
        "docs/arch/.meta.json",  # arch regeneration timestamp / commit sha
    }
)


def _normalize(path: str) -> str:
    """Strip whitespace and a leading ``./`` so prefix checks are stable."""
    return path.strip().removeprefix("./")


def is_non_deliverable_path(path: str) -> bool:
    """Return ``True`` if *path* is a planner diagram or auto-generated artifact.

    Planner diagrams are ``.likec4`` files under ``docs/architecture/``. Other
    files under that directory (e.g. a hand-written ``README.md``) are treated
    as real deliverables to avoid false positives.
    """
    p = _normalize(path)
    if not p:
        return False
    if p in _NON_DELIVERABLE_EXACT:
        return True
    if p.startswith("docs/architecture/") and p.endswith(".likec4"):
        return True
    return any(p.startswith(prefix) for prefix in _NON_DELIVERABLE_PREFIXES)


def substantive_paths(changed_paths: Iterable[str]) -> list[str]:
    """Return the changed paths that represent real deliverables (code/tests/assets/docs)."""
    out: list[str] = []
    for raw in changed_paths:
        p = _normalize(raw)
        if p and not is_non_deliverable_path(p):
            out.append(p)
    return out


def is_null_delivery(changed_paths: Sequence[str]) -> bool:
    """Return ``True`` when *changed_paths* is a null delivery.

    A null delivery has at least one changed file and **zero** substantive
    files. An empty change set is **not** a null delivery — that is a zero-diff
    result, handled separately by the zero-commit / zero-diff guards.
    """
    cleaned = [p for p in (_normalize(c) for c in changed_paths) if p]
    if not cleaned:
        return False
    return not substantive_paths(cleaned)
