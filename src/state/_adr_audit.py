"""State accessors for AdrTouchpointAuditorLoop (ADR-0056) and
AdrConformanceLoop (ADR-0098)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class AdrAuditStateMixin:
    """Cursor (last-scanned merged-PR ISO timestamp) + per-finding repair attempts.

    Also carries the sibling AdrConformanceLoop (ADR-0098) attempt/rollup
    state under the `adr_conformance_*` namespace.
    """

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_adr_audit_cursor(self) -> str:
        return self._data.adr_audit_cursor

    def set_adr_audit_cursor(self, cursor: str) -> None:
        self._data.adr_audit_cursor = cursor
        self.save()

    def get_adr_audit_attempts(self, key: str) -> int:
        return int(self._data.adr_audit_attempts.get(key, 0))

    def inc_adr_audit_attempts(self, key: str) -> int:
        current = int(self._data.adr_audit_attempts.get(key, 0)) + 1
        attempts = dict(self._data.adr_audit_attempts)
        attempts[key] = current
        self._data.adr_audit_attempts = attempts
        self.save()
        return current

    def clear_adr_audit_attempts(self, key: str) -> None:
        attempts = dict(self._data.adr_audit_attempts)
        attempts.pop(key, None)
        self._data.adr_audit_attempts = attempts
        self.save()

    # Per-ADR rollup tracking (#8987) — see ADR-0056 amendment.

    def get_adr_rollup(self, adr_key: str) -> dict | None:
        """Return ``{'issue_number': int, 'pr_numbers': list[int]}`` or ``None``."""
        entry = self._data.adr_rollup_issues.get(adr_key)
        if not entry:
            return None
        return {
            "issue_number": int(entry.get("issue_number", 0)),
            "pr_numbers": list(entry.get("pr_numbers", [])),
        }

    def set_adr_rollup(
        self, adr_key: str, *, issue_number: int, pr_numbers: list[int]
    ) -> None:
        rollups = dict(self._data.adr_rollup_issues)
        rollups[adr_key] = {
            "issue_number": int(issue_number),
            "pr_numbers": sorted({int(n) for n in pr_numbers}),
        }
        self._data.adr_rollup_issues = rollups
        self.save()

    def clear_adr_rollup(self, adr_key: str) -> None:
        rollups = dict(self._data.adr_rollup_issues)
        rollups.pop(adr_key, None)
        self._data.adr_rollup_issues = rollups
        self.save()

    # AdrConformanceLoop (ADR-0098) — per-ADR remediation attempt counters +
    # rollup tracking. Mirrors the adr_audit_*/adr_rollup_* methods above
    # under a distinct storage namespace so conformance counters never
    # collide with touchpoint-audit counters.

    def inc_adr_conformance_attempts(self, adr_id: str) -> int:
        current = int(self._data.adr_conformance_attempts.get(adr_id, 0)) + 1
        attempts = dict(self._data.adr_conformance_attempts)
        attempts[adr_id] = current
        self._data.adr_conformance_attempts = attempts
        self.save()
        return current

    def clear_adr_conformance_attempts(self, adr_id: str) -> None:
        attempts = dict(self._data.adr_conformance_attempts)
        attempts.pop(adr_id, None)
        self._data.adr_conformance_attempts = attempts
        self.save()

    def get_adr_conformance_rollup(self, adr_id: str) -> dict | None:
        """Return ``{'issue_number': int}`` or ``None``."""
        entry = self._data.adr_conformance_rollup_issues.get(adr_id)
        if not entry:
            return None
        return {"issue_number": int(entry.get("issue_number", 0))}

    def set_adr_conformance_rollup(self, adr_id: str, *, issue_number: int) -> None:
        rollups = dict(self._data.adr_conformance_rollup_issues)
        rollups[adr_id] = {"issue_number": int(issue_number)}
        self._data.adr_conformance_rollup_issues = rollups
        self.save()

    def clear_adr_conformance_rollup(self, adr_id: str) -> None:
        rollups = dict(self._data.adr_conformance_rollup_issues)
        rollups.pop(adr_id, None)
        self._data.adr_conformance_rollup_issues = rollups
        self.save()
