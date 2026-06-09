"""RollupIssueManager — one open issue per subject, auto-closed on resolve.

#9359 issue-hygiene. Most caretaker loops file a GitHub find-issue when a
condition goes bad but never close it when the condition recovers, so resolved
conditions accumulate as stale open issues (the bulk of the backlog this
session pruned). This centralizes the proven rollup pattern from
``AdrTouchpointAuditorLoop`` / ``FakeCoverageAuditorLoop`` /
``LiveCorpusReplayLoop``:

- :meth:`ensure` — create ONE issue per subject, or update its body in place
  when the variable content changes (no-op when unchanged).
- :meth:`resolve` — close the issue when the condition clears (idempotent).
- :meth:`resolve_all_except` — for set-based reconcilers, close every tracked
  subject that is no longer active.

Titles MUST be stable (no counts / SHAs / PR numbers) — variable content goes in
the BODY, which :meth:`ensure` diffs via a content hash so redundant
``update_issue_body`` calls are skipped. State lives under
``state.rollup_issues`` keyed ``"{namespace}:{subject}"``; if that state is lost
but the issue still exists, ``PRManager.create_issue`` returns the existing
number (exact-title dedup), so :meth:`ensure` re-adopts it rather than filing a
duplicate.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.rollup_issue_manager")


def _content_hash(title: str, body: str) -> str:
    return hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()


class RollupIssueManager:
    """Keep one open GitHub issue per subject under a namespace."""

    def __init__(
        self,
        *,
        pr: PRPort,
        state: StateTracker,
        namespace: str,
        labels: list[str],
    ) -> None:
        self._pr = pr
        self._state = state
        self._namespace = namespace
        self._labels = list(labels)

    def _key(self, subject: str) -> str:
        return f"{self._namespace}:{subject}"

    async def ensure(
        self,
        subject: str,
        *,
        title: str,
        body: str,
        extra_labels: list[str] | None = None,
    ) -> int:
        """Keep ONE open issue for *subject*.

        Creates it on first use, updates the body in place when *body* changes,
        and no-ops when unchanged. Returns the issue number (``0`` on a create
        failure — caller should retry next tick).
        """
        key = self._key(subject)
        content_hash = _content_hash(title, body)
        tracked = self._state.get_rollup_issue(key)
        if tracked and tracked["issue_number"]:
            number = tracked["issue_number"]
            if tracked["content_hash"] != content_hash:
                await self._pr.update_issue_body(number, body)
                self._state.set_rollup_issue(
                    key, issue_number=number, content_hash=content_hash
                )
            return number

        labels = self._labels + list(extra_labels or [])
        number = await self._pr.create_issue(title, body, labels)
        if number and number != 0:
            self._state.set_rollup_issue(
                key, issue_number=number, content_hash=content_hash
            )
        else:
            # create_issue's documented 0-sentinel: don't persist — retry next
            # tick rather than latch a phantom issue #0.
            logger.warning(
                "rollup ensure: create_issue returned 0 for %r; will retry", key
            )
        return number

    async def resolve(self, subject: str, *, comment: str | None = None) -> bool:
        """Close the tracked issue for *subject* and clear its state.

        Idempotent — a no-op (returns ``False``) when nothing is tracked, so it
        is safe to call on every clean tick. Returns ``True`` if it closed an
        issue.
        """
        key = self._key(subject)
        tracked = self._state.get_rollup_issue(key)
        if not (tracked and tracked["issue_number"]):
            return False
        number = tracked["issue_number"]
        if comment:
            await self._pr.post_comment(number, comment)
        await self._pr.close_issue(number)
        self._state.clear_rollup_issue(key)
        return True

    async def resolve_all_except(
        self, active_subjects: Iterable[str], *, comment: str | None = None
    ) -> int:
        """Close every tracked subject in this namespace NOT in *active_subjects*.

        For set-based reconcilers (e.g. open security alerts, currently-flaky
        tests): pass the still-active subjects; everything else self-closes.
        Returns the number of issues closed.
        """
        active_keys = {self._key(s) for s in active_subjects}
        closed = 0
        for key in self._state.get_rollup_issue_keys(self._namespace):
            if key in active_keys:
                continue
            subject = key[len(self._namespace) + 1 :]
            if await self.resolve(subject, comment=comment):
                closed += 1
        return closed
