"""Unit + guard tests for the principle register (#11077)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from principle_register import (
    Holding,
    load_principles,
    stale_holdings,
)

_REPO_ROOT = Path(__file__).parent.parent


def _write(tmp_path: Path, text: str) -> Path:
    control = tmp_path / "control"
    control.mkdir(exist_ok=True)
    (control / "principles.yaml").write_text(text)
    return tmp_path


class TestLoading:
    def test_setpoint_held_requires_enforcement(self, tmp_path: Path) -> None:
        _write(tmp_path, "p:\n  holding: setpoint\n")
        with pytest.raises(ValueError, match="names no enforcement"):
            load_principles(tmp_path)

    def test_human_held_requires_currency_contract(self, tmp_path: Path) -> None:
        # held_by without currency_days/last_exercised = the decay path.
        _write(tmp_path, "p:\n  holding: human\n  held_by: travis\n")
        with pytest.raises(ValueError, match="currency requirement"):
            load_principles(tmp_path)

    def test_middle_state_is_unrepresentable(self, tmp_path: Path) -> None:
        # "measured but not enforced" has no encoding: an invalid holding
        # refuses to load (fail-closed — the register is guard-tested).
        _write(tmp_path, "p:\n  holding: measured\n")
        with pytest.raises(ValueError):
            load_principles(tmp_path)

    def test_valid_entries_load(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "enc:\n  holding: setpoint\n  enforced_by: make audit\n"
            "held:\n  holding: human\n  held_by: travis\n"
            "  currency_days: 90\n  last_exercised: '2026-07-30'\n"
            "  instruments: [erosion]\n",
        )
        entries = load_principles(tmp_path)
        assert entries["enc"].holding is Holding.SETPOINT
        assert entries["held"].currency_days == 90
        assert entries["held"].instruments == ("erosion",)


class TestCurrency:
    def _entries(self, tmp_path: Path, last_exercised: str):
        _write(
            tmp_path,
            "held:\n  holding: human\n  held_by: travis\n"
            f"  currency_days: 90\n  last_exercised: '{last_exercised}'\n",
        )
        return load_principles(tmp_path)

    def test_within_currency_is_quiet(self, tmp_path: Path) -> None:
        now = datetime(2026, 8, 13, tzinfo=UTC)
        entries = self._entries(tmp_path, "2026-07-30")
        assert stale_holdings(entries, now=now) == []

    def test_past_currency_is_stale_with_overdue_days(self, tmp_path: Path) -> None:
        # Fixed instants both sides — never a fixture date vs real now()
        # (TEST-WALLCLOCK-TIMEBOMB-001).
        exercised = datetime(2026, 7, 30, tzinfo=UTC)
        now = exercised + timedelta(days=100)
        entries = self._entries(tmp_path, "2026-07-30")
        stale = stale_holdings(entries, now=now)
        assert len(stale) == 1
        assert stale[0].principle_id == "held"
        assert stale[0].held_by == "travis"
        assert stale[0].days_overdue == 10

    def test_setpoint_held_never_stales(self, tmp_path: Path) -> None:
        _write(tmp_path, "enc:\n  holding: setpoint\n  enforced_by: make audit\n")
        entries = load_principles(tmp_path)
        far_future = datetime(2030, 1, 1, tzinfo=UTC)
        assert stale_holdings(entries, now=far_future) == []


class TestRepoRegister:
    def test_repo_register_loads_and_is_fully_classified(self) -> None:
        # The real, versioned register must always parse — loading IS the
        # nothing-in-the-middle guard (malformed/middle entries raise).
        entries = load_principles(_REPO_ROOT)
        assert len(entries) >= 13

    def test_adr0044_contract_is_setpoint_held(self) -> None:
        entries = load_principles(_REPO_ROOT)
        for pid in [f"P{i}" for i in range(1, 11)]:
            matches = [e for k, e in entries.items() if k.startswith(f"{pid}-")]
            assert matches, f"ADR-0044 {pid} missing from control/principles.yaml"
            assert matches[0].holding is Holding.SETPOINT

    def test_graded_principles_are_explicitly_human_held(self) -> None:
        entries = load_principles(_REPO_ROOT)
        for pid in ("keep-it-simple", "prefer-what-exists", "improve-by-rate"):
            assert entries[pid].holding is Holding.HUMAN
            assert entries[pid].currency_days > 0
            assert entries[pid].instruments  # measured AND held — never neither
