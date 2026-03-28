"""State accessors for code grooming settings and filed findings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from models import CodeGroomingSettings, GroomingFiledFinding

if TYPE_CHECKING:
    from models import StateData


class CodeGroomingStateMixin:
    """Mixed into StateTracker for code grooming persistence."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_code_grooming_settings(self) -> CodeGroomingSettings:
        """Return current code grooming settings."""
        return CodeGroomingSettings.model_validate(
            self._data.code_grooming_settings.model_dump()
        )

    def set_code_grooming_settings(self, settings: CodeGroomingSettings) -> None:
        """Persist code grooming settings."""
        self._data.code_grooming_settings = settings
        self.save()

    def get_grooming_filed_findings(self) -> list[GroomingFiledFinding]:
        """Return all previously filed grooming findings."""
        return list(self._data.code_grooming_filed)

    def add_grooming_filed_finding(self, finding: GroomingFiledFinding) -> None:
        """Record a newly filed grooming finding."""
        self._data.code_grooming_filed.append(finding)
        self.save()

    def has_grooming_dedup_key(self, dedup_key: str) -> bool:
        """Check if a finding with this dedup key was already filed."""
        return any(f.dedup_key == dedup_key for f in self._data.code_grooming_filed)
