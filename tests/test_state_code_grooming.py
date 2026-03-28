"""Tests for the CodeGroomingStateMixin."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import CodeGroomingSettings, GroomingFiledFinding, GroomingPriority
from state import StateTracker


@pytest.fixture()
def tracker(tmp_path: Path) -> StateTracker:
    state_file = tmp_path / "state.json"
    return StateTracker(state_file)


class TestCodeGroomingSettings:
    def test_get_default_settings(self, tracker: StateTracker):
        settings = tracker.get_code_grooming_settings()
        assert settings.max_issues_per_cycle == 5
        assert settings.min_priority == GroomingPriority.P1
        assert settings.dry_run is False

    def test_set_and_get_settings(self, tracker: StateTracker):
        custom = CodeGroomingSettings(
            max_issues_per_cycle=3,
            min_priority=GroomingPriority.P0,
            enabled_audits=["code_quality"],
            dry_run=True,
        )
        tracker.set_code_grooming_settings(custom)
        loaded = tracker.get_code_grooming_settings()
        assert loaded.max_issues_per_cycle == 3
        assert loaded.min_priority == GroomingPriority.P0
        assert loaded.enabled_audits == ["code_quality"]
        assert loaded.dry_run is True

    def test_settings_persist_across_reload(self, tmp_path: Path):
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        custom = CodeGroomingSettings(max_issues_per_cycle=10, dry_run=True)
        tracker.set_code_grooming_settings(custom)

        tracker2 = StateTracker(state_file)
        loaded = tracker2.get_code_grooming_settings()
        assert loaded.max_issues_per_cycle == 10
        assert loaded.dry_run is True


class TestGroomingFiledFindings:
    def test_empty_by_default(self, tracker: StateTracker):
        assert tracker.get_grooming_filed_findings() == []

    def test_add_and_get(self, tracker: StateTracker):
        finding = GroomingFiledFinding(
            dedup_key="abc123",
            issue_number=42,
            title="[Grooming] P1: missing tests",
            priority=GroomingPriority.P1,
        )
        tracker.add_grooming_filed_finding(finding)
        findings = tracker.get_grooming_filed_findings()
        assert len(findings) == 1
        assert findings[0].dedup_key == "abc123"
        assert findings[0].issue_number == 42

    def test_has_dedup_key(self, tracker: StateTracker):
        assert tracker.has_grooming_dedup_key("abc123") is False
        finding = GroomingFiledFinding(
            dedup_key="abc123",
            issue_number=42,
            title="test",
            priority=GroomingPriority.P1,
        )
        tracker.add_grooming_filed_finding(finding)
        assert tracker.has_grooming_dedup_key("abc123") is True
        assert tracker.has_grooming_dedup_key("xyz789") is False

    def test_multiple_findings(self, tracker: StateTracker):
        for i in range(3):
            tracker.add_grooming_filed_finding(
                GroomingFiledFinding(
                    dedup_key=f"key_{i}",
                    issue_number=100 + i,
                    title=f"finding {i}",
                    priority=GroomingPriority.P2,
                )
            )
        findings = tracker.get_grooming_filed_findings()
        assert len(findings) == 3
        assert all(tracker.has_grooming_dedup_key(f"key_{i}") for i in range(3))
