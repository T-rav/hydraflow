"""Per-tick issue-filing budget shared across background loops (#10767, #10777).

Bounds the number of GitHub-issue *filing* calls (``PRPort.create_issue``) a
background loop makes in a single tick. Without such a bound a loop that files
one issue per finding floods the board when a burst of findings surfaces at
once — ``WikiRotDetectorLoop`` filed ~7 ``hydraflow-find`` issues in a tick
before #10767 added the first budget. #10777 generalizes the pattern: every
issue-filing loop must either carry a cap or be provably bounded by design
(guard: ``tests/regressions/test_issue_10777_filing_cap.py``).

Two shapes build on :class:`FilingBudget`:

* **Summary-on-overflow** — a loop backed by a persistent ``seen`` store
  (``DedupStore``) records each over-cap subject so it is not re-filed
  individually, then calls :func:`file_overflow_summary` once to surface the
  whole overflow batch as a SINGLE issue (the #10767 shape).
* **Defer-and-retry** — a loop with no such store simply skips over-cap
  findings this tick (recording no state), so they surface on a later tick
  when the budget refreshes (the ``erosion_metrics``/``escape_ledger`` shape).

Either way the loop's per-tick blast radius is bounded by construction rather
than by how conservative each finding extractor happens to be.

Originally lived in ``wiki_rot_detector_loop`` (#10767); extracted here so the
abstraction is shared, not copy-pasted, across every filing loop (#10777).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

# Cap the number of over-budget bullet lines rendered into a summary issue's
# body; the count is always stated in full even when the list is truncated.
_SUMMARY_MAX_LINES = 50


@dataclass
class FilingBudget:
    """Per-tick issue-filing budget (issue #10767).

    Bounds only the number of issue *filing* calls a loop makes per tick. Once
    the cap is reached, callers collect further findings into :attr:`overflow`
    (for the summary shape) or skip them (for the defer shape) instead of
    filing one issue each, so the loop's blast radius is bounded by
    construction.

    ``cap`` is validated ``ge=1`` in config, so :meth:`allow` always leaves
    room for at least one filing before the overflow path engages.
    """

    cap: int
    filed: int = 0
    overflow: list[str] = field(default_factory=list)

    def allow(self) -> bool:
        """Return ``True`` while the tick still has filing budget."""
        return self.filed < self.cap

    def note_filed(self) -> None:
        """Record that one issue was filed this tick."""
        self.filed += 1

    def note_overflow(self, line: str) -> None:
        """Collect one over-cap finding for the summary issue."""
        self.overflow.append(line)


class _SupportsDedup(Protocol):
    """Structural type for a ``DedupStore``-like persistent seen-key set."""

    def get(self) -> set[str]: ...

    def set_all(self, values: set[str]) -> None: ...


def overflow_line(subject: str, detail: str = "") -> str:
    """Render one bullet line for a per-tick-cap summary issue body."""
    if detail:
        return f"- `{subject}` — {detail}"
    return f"- `{subject}`"


def overflow_digest(lines: Sequence[str]) -> str:
    """A short, stable content digest of *lines* for summary-issue dedup.

    Non-cryptographic — ``usedforsecurity=False`` marks it so (bandit B324).
    """
    joined = "\n".join(sorted(lines))
    return hashlib.sha1(joined.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


async def file_overflow_summary(
    *,
    create_issue: Callable[[str, str, list[str]], Awaitable[int]],
    dedup: _SupportsDedup,
    budget: FilingBudget,
    key_prefix: str,
    labels: Sequence[str],
    title: str,
    intro: str,
) -> int:
    """File ONE summary issue for findings that overflowed the per-tick cap.

    When more than ``budget.cap`` findings surface in a single tick, the caller
    records each over-cap subject in *dedup* (so it is not re-filed
    individually) and collects a bullet line via :meth:`FilingBudget.note_overflow`;
    this then folds the whole batch into a single ``create_issue`` call instead
    of one issue per finding (#10767). The summary is deduped by a digest of its
    own contents (``{key_prefix}:summary:{digest}``) so an unchanged overflow set
    is not re-filed on later ticks. Returns ``1`` if a summary was filed, else
    ``0``.

    Honors ``create_issue``'s documented 0-sentinel (``ports.py``): when the gh
    call fails without raising, the dedup key is left unrecorded so the summary
    is retried next tick rather than silently swallowed.
    """
    if not budget.overflow:
        return 0

    lines = sorted(budget.overflow)
    dedup_key = f"{key_prefix}:summary:{overflow_digest(lines)}"
    seen = dedup.get()
    if dedup_key in seen:
        return 0

    count = len(lines)
    shown = lines[:_SUMMARY_MAX_LINES]
    body_lines = [
        intro,
        "",
        (
            f"{count} finding(s) exceeded the per-tick filing cap of "
            f"`{budget.cap}` and are summarized here instead of one issue each. "
            "Each is already recorded and will not be re-filed individually; "
            "resolve or prune them, then close this issue."
        ),
        "",
        "### Findings over the per-tick cap",
        "",
        *shown,
    ]
    if count > len(shown):
        body_lines.append(f"- …and {count - len(shown)} more.")

    issue_number = await create_issue(title, "\n".join(body_lines), list(labels))
    if not issue_number:
        # 0-sentinel: gh failed without raising. Leave the dedup key unspent so
        # the summary is retried next tick rather than lost.
        return 0

    seen.add(dedup_key)
    dedup.set_all(seen)
    return 1
