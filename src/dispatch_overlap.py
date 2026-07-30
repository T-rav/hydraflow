"""Dispatch-time scope-overlap detection for concurrent build units (#10778).

Batch / parallel-build dispatch hands ready issues to a pool of concurrent
implement workers (``ImplementPhase.run_batch`` → ``run_refilling_pool``). Two
issues dispatched together can predict-touch the SAME scope — the same
referenced issue number or the same source files — and, built in ignorance of
each other, resolve it CONTRADICTORILY. The forcing case (#10754
double-resolution): #10772 and #10773 were dispatched in one batch, both touched
issue #10754 and the same ``wiki_rot_*.py`` files, and one added a tool + wiki
citations while the other removed those citations assuming no tool existed. A
manual rebase + semantic reconcile followed.

ADR-0002's ``hydraflow-in-progress`` build-claim marker closes the *same-issue*
double-pick class (two actors building the SAME issue). This module closes the
sibling *scope-overlap* class: two DIFFERENT issues whose predicted scopes
intersect. It is a cheap, in-memory, pre-flight admission check consulted at the
same dispatch seam as the in-flight claim. On overlap the dispatcher SERIALIZES
— it holds the second unit and re-dispatches it on a later refill round, once the
first unit frees its slot — instead of building both at once. This extends the
existing dispatch-dedup family (the duplicate-issue parallel-build-collision
guard) rather than adding a parallel mechanism.

Signals, cheapest-and-most-reliable first:

1. **Shared referenced issue number** — the primary, low-false-positive signal.
   Two units name the same ``#N`` in title/body (or one unit *is* the issue the
   other references). This is the exact #10754 double-resolution cause and is
   reliably extractable from issue text.
2. **Shared predicted file path** — a secondary, best-effort heuristic. Both
   units mention the *same* concrete code-file path token. Deliberately
   conservative: only exact normalized path tokens match (no basename fuzzing),
   and ubiquitous files (``__init__.py``, ``README.md`` …) never count — file
   *prediction* from prose is inherently less reliable than an explicit issue
   reference, and a false positive costs throughput (a needless serialization).

Design invariants that keep the guard throughput-safe:

- An empty scope (no references, no concrete file mentions) can never overlap
  anything, so a bare issue is never held.
- Two DISTINCT issues never overlap on their own ids alone — only on a *shared*
  reference or a reference to each other.
- The tracker is pure and process-local; it holds no I/O and dies with the
  process. Its ``reserve`` set contains only units currently dispatched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from models import Task

# A GitHub-style issue reference: ``#`` immediately followed by digits, not part
# of a larger token (so ``##``, ``word#5`` and Markdown ``# Heading`` don't
# match). Ordinal mentions like ``step #1`` are tolerated — a rare, cheap false
# positive (a serialization) is preferable to missing a real cross-reference.
_ISSUE_REF = re.compile(r"(?<![\w#])#(\d+)")

# "Parent Epic: #N" style back-references are structural epic membership, not a
# predicted scope overlap; two siblings sharing a parent must not serialize on
# the parent alone. Stripped from the referenced set (belt-and-suspenders with
# ``Task.parent_epic``).
_PARENT_EPIC = re.compile(r"parent\s+epic[:\s#]*#?(\d+)", re.IGNORECASE)

# A concrete code/config file path token: a path-like run ending in a known
# source extension. ``wiki_rot_*.py`` (glob), ``src/foo.py`` (qualified) and
# ``config.py`` (bare) all match; surrounding backticks/quotes/parens are not in
# the charset, so ``findall`` grabs just the path.
_PATH_TOKEN = re.compile(
    r"[A-Za-z0-9_][A-Za-z0-9_./*-]*\.(?:py|tsx?|jsx?|ya?ml|md|sh|toml|sql)"
)

# Characters to trim off a captured path token (trailing sentence punctuation).
_STRIP = "`'\"()<>[],;:. "

# Basenames too ubiquitous to be a reliable overlap signal — a shared mention of
# any of these predicts nothing about touching the same code.
_GENERIC_FILES: frozenset[str] = frozenset(
    {
        "__init__.py",
        "__main__.py",
        "conftest.py",
        "setup.py",
        "readme.md",
        "claude.md",
        "changelog.md",
        "index.md",
        "makefile",
        "pyproject.toml",
        "package.json",
        "tsconfig.json",
    }
)


@dataclass(frozen=True)
class DispatchScope:
    """The predicted scope of a single build unit.

    ``referenced_issues`` excludes the unit's own id and any parent-epic id;
    ``files`` holds normalized, non-generic path tokens for the exact-match file
    signal.
    """

    issue_id: int
    referenced_issues: frozenset[int]
    files: frozenset[str]

    @property
    def issue_scope(self) -> frozenset[int]:
        """The unit's own id plus every distinct issue it references."""
        return self.referenced_issues | {self.issue_id}


@dataclass(frozen=True)
class OverlapReason:
    """Why two scopes overlap. ``kind`` is ``"issue"`` or ``"file"``."""

    kind: str
    detail: str


@dataclass(frozen=True)
class HoldDecision:
    """A dispatch was held because *held_id* overlaps in-flight *blocking_id*."""

    held_id: int
    blocking_id: int
    reason: OverlapReason


def _extract_files(text: str) -> frozenset[str]:
    """Return the set of normalized, non-generic file path tokens in *text*."""
    files: set[str] = set()
    for raw in _PATH_TOKEN.findall(text):
        token = raw.strip(_STRIP).lower()
        if not token:
            continue
        basename = token.rsplit("/", 1)[-1]
        if basename in _GENERIC_FILES:
            continue
        files.add(token)
    return frozenset(files)


def compute_scope(task: Task) -> DispatchScope:
    """Derive the predicted :class:`DispatchScope` of *task* from its text.

    Pure and cheap (regex over title + body). References to the task's own id
    and to its parent epic are excluded so a unit never overlaps itself and
    epic siblings do not serialize on their shared parent.
    """
    text = f"{task.title}\n{task.body}"
    referenced = {int(n) for n in _ISSUE_REF.findall(text)}
    referenced.discard(task.id)
    if task.parent_epic is not None:
        referenced.discard(task.parent_epic)
    for match in _PARENT_EPIC.finditer(text):
        referenced.discard(int(match.group(1)))
    return DispatchScope(
        issue_id=task.id,
        referenced_issues=frozenset(referenced),
        files=_extract_files(text),
    )


def _format_issue_refs(shared: frozenset[int]) -> str:
    return ", ".join(f"#{n}" for n in sorted(shared))


def find_scope_overlap(
    candidate: DispatchScope, reserved: DispatchScope
) -> OverlapReason | None:
    """Return why *candidate* overlaps *reserved*, or ``None`` if disjoint.

    The issue signal is checked first (most reliable); the exact-file signal is
    the fallback. Two distinct units with no shared reference and no shared
    concrete file are disjoint and dispatch concurrently.
    """
    shared_issues = candidate.issue_scope & reserved.issue_scope
    if shared_issues:
        return OverlapReason("issue", _format_issue_refs(shared_issues))
    shared_files = candidate.files & reserved.files
    if shared_files:
        return OverlapReason("file", ", ".join(sorted(shared_files)))
    return None


class DispatchOverlapTracker:
    """Tracks the scopes of currently-dispatched units and admits or holds new ones.

    Process-local and pure: :meth:`reserve_or_hold` is the pre-flight admission
    check called synchronously at dispatch time (before a unit is handed to a
    worker slot), and :meth:`release` is called when a unit's worker exits. The
    check is synchronous with no ``await`` points so a batch of slots filled in
    one refill round is admitted atomically — the second of two co-dispatched
    overlapping units sees the first already reserved and is held.
    """

    def __init__(self) -> None:
        self._reserved: dict[int, DispatchScope] = {}

    def reserve_or_hold(self, task: Task) -> HoldDecision | None:
        """Reserve *task*'s scope, or return the :class:`HoldDecision` that holds it.

        ``None`` — the task did not overlap any in-flight unit; its scope is now
        reserved and it is safe to dispatch. A :class:`HoldDecision` — the task
        overlaps an already-reserved unit and was NOT reserved; the caller
        should serialize it (hold and re-dispatch on a later round). Held units
        are never reserved, so they cannot block each other.
        """
        scope = compute_scope(task)
        for reserved in self._reserved.values():
            reason = find_scope_overlap(scope, reserved)
            if reason is not None:
                return HoldDecision(
                    held_id=task.id, blocking_id=reserved.issue_id, reason=reason
                )
        self._reserved[task.id] = scope
        return None

    def release(self, issue_id: int) -> None:
        """Release a unit's reservation when its worker exits. Idempotent."""
        self._reserved.pop(issue_id, None)

    @property
    def reserved_ids(self) -> frozenset[int]:
        """The ids of units currently reserved (dispatched, not yet released)."""
        return frozenset(self._reserved)
