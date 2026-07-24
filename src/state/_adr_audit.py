"""State accessors for AdrTouchpointAuditorLoop (ADR-0056) and
AdrConformanceLoop (ADR-0100)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class AdrAuditStateMixin:
    """Cursor (last-scanned merged-PR ISO timestamp) + per-finding repair attempts.

    Also carries the sibling AdrConformanceLoop (ADR-0100) attempt/rollup
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
        """Return ``{'issue_number': int, 'pr_numbers': list[int],
        'adr_numbers': list[int]}`` or ``None``.

        ``adr_numbers`` (#10457) is only ever non-empty for a ``FLEET-<pr>``
        rollup — the member ADR numbers the resolver loop needs to triage
        each one. It defaults to ``[]`` for per-ADR (``ADR-NNNN``) rollups
        and for any rollup persisted before this field existed.
        """
        entry = self._data.adr_rollup_issues.get(adr_key)
        if not entry:
            return None
        return {
            "issue_number": int(entry.get("issue_number", 0)),
            "pr_numbers": list(entry.get("pr_numbers", [])),
            "adr_numbers": list(entry.get("adr_numbers", [])),
        }

    def all_adr_rollups(self) -> dict[str, dict]:
        """Return a normalized copy of every tracked rollup, keyed by ``ADR-NNNN``.

        Used by the auditor's stale-rollup reconciliation pass (#9622) to
        re-evaluate rollups whose ADR did not drift in the current scan
        window — the original contributor PRs may predate the cursor and are
        never rescanned by ``compute_drift_by_adr``.
        """
        return {
            key: {
                "issue_number": int(entry.get("issue_number", 0)),
                "pr_numbers": list(entry.get("pr_numbers", [])),
                "adr_numbers": list(entry.get("adr_numbers", [])),
            }
            for key, entry in self._data.adr_rollup_issues.items()
        }

    def set_adr_rollup(
        self,
        adr_key: str,
        *,
        issue_number: int,
        pr_numbers: list[int],
        adr_numbers: list[int] | None = None,
    ) -> None:
        rollups = dict(self._data.adr_rollup_issues)
        rollups[adr_key] = {
            "issue_number": int(issue_number),
            "pr_numbers": sorted({int(n) for n in pr_numbers}),
            "adr_numbers": sorted({int(n) for n in adr_numbers or []}),
        }
        self._data.adr_rollup_issues = rollups
        self.save()

    def clear_adr_rollup(self, adr_key: str) -> None:
        rollups = dict(self._data.adr_rollup_issues)
        rollups.pop(adr_key, None)
        self._data.adr_rollup_issues = rollups
        self.save()

    # AdrConformanceLoop (ADR-0100) — per-ADR remediation attempt counters +
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
