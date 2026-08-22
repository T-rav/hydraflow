"""State accessors for AdrConformanceLoop (ADR-0100).

Named ``_adr_audit`` for its original occupant, ``AdrTouchpointAuditorLoop``
(ADR-0056): its ``adr_audit_*`` cursor/attempt and ``adr_rollup_*`` accessors
were removed with the loop by ADR-0136. Only the conformance namespace remains.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class AdrAuditStateMixin:
    """AdrConformanceLoop (ADR-0100) attempt counters + per-ADR rollup tracking.

    Stored under the `adr_conformance_*` namespace, which was originally chosen
    to stay disjoint from the retired touchpoint-auditor counters (ADR-0136).
    """

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

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
