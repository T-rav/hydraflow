"""Shape classifier for the shadow corpus (issue #9354).

Classifies subprocess calls into three mutually exclusive categories:

- **MUTATING**: side-effecting commands (gh issue create, git push, …).
  Dropped at record time — they carry no shape or value information worth
  replaying.

- **VOLATILE**: live-state queries whose output changes with every
  run (gh issue list, gh search, gh api search/…).  Kept for *shape*
  validation only; raw-value differences are suppressed at compare time.

- **DETERMINISTIC**: stable single-entity lookups (gh pr view <N>,
  gh issue view <N>, gh pr checks <N>).  Full value comparison is safe.

The module is pure (no I/O, no imports from the rest of the codebase) so it
can be imported cheaply anywhere, including at record time inside
``ShadowCorpus.record``.
"""

from __future__ import annotations

from enum import StrEnum

# Key embedded in the drift dict returned by ``gh_shape_validator`` (and any
# future shape-only dispatcher) when Pydantic validation fails.  The
# compare-time suppression in ``LiveCorpusReplayLoop`` uses this key to
# distinguish shape failures (real drift) from raw-value differences
# (non-drift for VOLATILE shapes).
SHAPE_VERDICT_KEY = "shape_validation_failed"


class ShapeClass(StrEnum):
    MUTATING = "MUTATING"
    VOLATILE = "VOLATILE"
    DETERMINISTIC = "DETERMINISTIC"


# --------------------------------------------------------------------------
# gh command classification tables
# --------------------------------------------------------------------------

_GH_MUTATING_VERBS: frozenset[str] = frozenset(
    {
        "create",
        "comment",
        "merge",
        "close",
        "reopen",
        "delete",
        "edit",
        "assign",
        "unassign",
        "label",
        "unlabel",
        "pin",
        "unpin",
        "lock",
        "unlock",
        "transfer",
        "link",
        "unlink",
    }
)

_GH_VOLATILE_VERBS: frozenset[str] = frozenset({"list", "search"})

_GH_DETERMINISTIC_VERBS: frozenset[str] = frozenset({"view", "checks"})

# HTTP methods that mutate server state.
_HTTP_MUTATING_METHODS: frozenset[str] = frozenset({"POST", "PATCH", "PUT", "DELETE"})

# Substrings in gh api paths that signal a live-list/search endpoint.
_GH_API_VOLATILE_SUBSTRINGS: tuple[str, ...] = ("search",)

# --------------------------------------------------------------------------
# git command classification tables
# --------------------------------------------------------------------------

_GIT_MUTATING_SUBCOMMANDS: frozenset[str] = frozenset(
    {
        "push",
        "clone",
        "init",
        "add",
        "commit",
        "merge",
        "rebase",
        "reset",
        "restore",
        "fetch",
        "tag",
    }
)

# git worktree sub-verbs that mutate the worktree list.
_GIT_WORKTREE_MUTATING_VERBS: frozenset[str] = frozenset({"add", "remove", "prune"})


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def classify(adapter: str, command: str, args: list[str]) -> ShapeClass:
    """Classify ``(adapter, command, args)`` as MUTATING, VOLATILE, or
    DETERMINISTIC.

    Falls back to VOLATILE for unknown adapters/commands — conservative
    (preserves shape validation, suppresses spurious value drift).
    """
    if adapter == "github" and command == "gh":
        return _classify_gh(args)
    if adapter == "git" and command == "git":
        return _classify_git(args)
    return ShapeClass.VOLATILE


def is_value_comparable(cls: ShapeClass) -> bool:
    """Return True only for DETERMINISTIC shapes.

    VOLATILE shapes are kept for shape validation only; raw-value
    differences must be suppressed at compare time.  MUTATING shapes
    should never reach the corpus (dropped at record time), but if they
    do, suppressing their value comparison is safe.
    """
    return cls is ShapeClass.DETERMINISTIC


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------


def _classify_gh(args: list[str]) -> ShapeClass:
    if not args:
        return ShapeClass.VOLATILE

    subgroup = args[0]

    if subgroup == "api":
        return _classify_gh_api(args[1:])

    verb = args[1] if len(args) > 1 else ""

    if subgroup == "search" or verb in _GH_VOLATILE_VERBS:
        return ShapeClass.VOLATILE
    if verb in _GH_MUTATING_VERBS:
        return ShapeClass.MUTATING
    if verb in _GH_DETERMINISTIC_VERBS:
        return ShapeClass.DETERMINISTIC

    return ShapeClass.VOLATILE


def _classify_gh_api(path_and_flags: list[str]) -> ShapeClass:
    """Classify ``gh api <path> [flags…]``."""
    # Check for explicit mutating HTTP method flags first.
    for flag in ("-X", "--method"):
        try:
            idx = path_and_flags.index(flag)
        except ValueError:
            continue
        if (
            idx + 1 < len(path_and_flags)
            and path_and_flags[idx + 1].upper() in _HTTP_MUTATING_METHODS
        ):
            return ShapeClass.MUTATING

    # Inspect the path argument (first positional arg, if any).
    path = path_and_flags[0] if path_and_flags else ""
    for substr in _GH_API_VOLATILE_SUBSTRINGS:
        if substr in path:
            return ShapeClass.VOLATILE

    # Default gh api paths to VOLATILE (list endpoints, unknown paths).
    return ShapeClass.VOLATILE


def _classify_git(args: list[str]) -> ShapeClass:
    if not args:
        return ShapeClass.VOLATILE

    subcommand = args[0]

    if subcommand in _GIT_MUTATING_SUBCOMMANDS:
        return ShapeClass.MUTATING

    if subcommand == "worktree":
        verb = args[1] if len(args) > 1 else ""
        if verb in _GIT_WORKTREE_MUTATING_VERBS:
            return ShapeClass.MUTATING
        return ShapeClass.VOLATILE

    return ShapeClass.VOLATILE
