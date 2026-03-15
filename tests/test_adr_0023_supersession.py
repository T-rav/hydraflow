"""Tests for ADR-0023 supersession — validates the superseded ADR passes structural validation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from adr_pre_validator import ADRPreValidator

_ADR_DIR = Path(__file__).parent.parent / "docs" / "adr"


class TestAdr0023Supersession:
    """Verify the superseded ADR still satisfies structural validation rules."""

    def test_superseded_adr_passes_validation(self) -> None:
        """The superseded ADR must still pass pre-validation."""
        content = (_ADR_DIR / "0023-gate-triage-call-not-hitl-fallback.md").read_text()
        validator = ADRPreValidator()
        result = validator.validate(content)
        assert result.passed, f"Validation issues: {[i.message for i in result.issues]}"

    def test_sibling_adr_unchanged_and_valid(self) -> None:
        """The sibling ADR must remain valid after the supersession change."""
        content = (
            _ADR_DIR / "0023-auto-triage-toggle-must-gate-routing.md"
        ).read_text()
        validator = ADRPreValidator()
        result = validator.validate(content)
        assert result.passed, f"Validation issues: {[i.message for i in result.issues]}"
