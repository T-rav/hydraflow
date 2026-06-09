"""State accessors for RollupIssueManager (#9359 issue-hygiene).

Generic per-subject rollup-issue tracking so any caretaker loop can keep ONE
open GitHub issue per subject (create-once, update body on change) and close it
when the condition resolves — instead of leaving resolved-condition find-issues
to accumulate. Keyed by ``"{namespace}:{subject}"``; value is
``{"issue_number": int, "content_hash": str}``.

This is intentionally a NEW, generic field separate from the loop-specific
``adr_rollup_issues`` / ``fake_coverage_rollup_issues`` (those already work and
have their own schemas — re-plumbing them is out of scope).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class RollupIssueStateMixin:
    """Generic ``{namespace}:{subject}`` -> rollup-issue tracking."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_rollup_issue(self, key: str) -> dict | None:
        """Return ``{"issue_number": int, "content_hash": str}`` or ``None``."""
        entry = self._data.rollup_issues.get(key)
        if not entry:
            return None
        return {
            "issue_number": int(entry.get("issue_number", 0)),
            "content_hash": str(entry.get("content_hash", "")),
        }

    def set_rollup_issue(
        self, key: str, *, issue_number: int, content_hash: str
    ) -> None:
        rollups = dict(self._data.rollup_issues)
        rollups[key] = {
            "issue_number": int(issue_number),
            "content_hash": content_hash,
        }
        self._data.rollup_issues = rollups
        self.save()

    def clear_rollup_issue(self, key: str) -> None:
        if key in self._data.rollup_issues:
            rollups = dict(self._data.rollup_issues)
            rollups.pop(key, None)
            self._data.rollup_issues = rollups
            self.save()

    def get_rollup_issue_keys(self, namespace: str) -> list[str]:
        """All tracked keys under ``namespace`` (i.e. ``"{namespace}:..."``)."""
        prefix = f"{namespace}:"
        return [k for k in self._data.rollup_issues if k.startswith(prefix)]
