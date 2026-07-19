"""State accessors for IssueRefinementLoop (spec #9957).

Persists the small change-detection index (NOT the engine's richer runtime
``RefinementIssue`` view — see ``src/issue_refinement.py``), the judged-pair cache
(newest-5000 cap), the weekly full-sweep marker, and the rolling digest
issue number.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from models import StateData

# Newest-N cap on the judged-pair cache. A dropped (oldest) key simply gets
# re-judged if the pair recurs — dedup invalidation lives in the pair_key's
# embedded body hashes, not in cache retention.
_MAX_JUDGED_PAIRS = 5000


class IssueRefinementStateMixin:
    """Change-detection index + judged-pair cache + full-sweep marker + digest issue."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    # --- change-detection index ---

    def get_refinement_index(self) -> dict[str, dict[str, str]]:
        """Return a copy of the persisted per-issue index.

        Keyed by issue number (str); value is
        ``{"title_hash", "body_hash", "updated_at"}``.
        """
        return {k: dict(v) for k, v in self._data.refinement_index.items()}

    def set_refinement_index(self, index: Mapping[str, Mapping[str, str]]) -> None:
        """Overwrite the persisted index with *index* and persist."""
        self._data.refinement_index = {k: dict(v) for k, v in index.items()}
        self.save()

    # --- judged-pair cache ---

    def get_judged_pairs(self) -> list[str]:
        """Return a copy of the judged-pair cache keys, oldest first."""
        return list(self._data.refinement_judged_pairs)

    def add_judged_pairs(self, keys: Iterable[str]) -> None:
        """Append newly-judged pair keys, de-duplicated, capped at the newest 5000.

        A key already present keeps its original (older) position — only
        genuinely new keys are appended, in the order given. When the
        combined list exceeds ``_MAX_JUDGED_PAIRS`` the OLDEST entries are
        dropped first, so insertion order is preserved among the entries
        that survive the prune.
        """
        existing = self._data.refinement_judged_pairs
        seen = set(existing)
        merged = list(existing)
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            merged.append(key)
        if len(merged) > _MAX_JUDGED_PAIRS:
            merged = merged[-_MAX_JUDGED_PAIRS:]
        self._data.refinement_judged_pairs = merged
        self.save()

    # --- weekly full-sweep marker ---

    def get_refinement_last_full_sweep(self) -> datetime | None:
        """Return the last full-sweep timestamp as a tz-aware ``datetime``.

        A naive-stored timestamp (no offset) is assumed UTC rather than left
        naive, so callers can always compare it against an aware ``now``
        without risking ``TypeError``. Returns ``None`` when never run or the
        stored value doesn't parse as ISO-8601.
        """
        raw = self._data.refinement_last_full_sweep
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed

    def set_refinement_last_full_sweep(self, when: datetime) -> None:
        """Persist *when* (should be tz-aware — pass ``datetime.now(UTC)``)."""
        self._data.refinement_last_full_sweep = when.isoformat()
        self.save()

    # --- rolling digest issue ---

    def get_refinement_digest_issue(self) -> int:
        """Return the digest issue number, or 0 if not yet created."""
        return self._data.refinement_digest_issue

    def set_refinement_digest_issue(self, number: int) -> None:
        self._data.refinement_digest_issue = number
        self.save()

    # --- open operator proposals (carried across ticks) ---

    def get_refinement_open_proposals(self) -> list[dict[str, Any]]:
        """Return a copy of the still-open operator questions.

        Each entry is a ``dup`` or ``priority`` record (see ``StateData.
        refinement_open_proposals``). The loop merges this tick's new proposals in,
        prunes entries whose issues left the backlog, and renders the whole
        set in the digest so an operator question first raised on an earlier
        tick keeps showing until it's actioned or its issue closes.
        """
        return [dict(p) for p in self._data.refinement_open_proposals]

    def set_refinement_open_proposals(
        self, proposals: Iterable[Mapping[str, Any]]
    ) -> None:
        """Overwrite the persisted open-proposals list with *proposals*."""
        self._data.refinement_open_proposals = [dict(p) for p in proposals]
        self.save()
