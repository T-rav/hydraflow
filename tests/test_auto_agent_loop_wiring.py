"""Five-checkpoint wiring assertions for auto_agent_preflight (ADR-0049)."""

from __future__ import annotations

from pathlib import Path

from dashboard_routes._common import _INTERVAL_BOUNDS


def test_interval_bounds_registered() -> None:
    assert "auto_agent_preflight" in _INTERVAL_BOUNDS
    assert _INTERVAL_BOUNDS["auto_agent_preflight"] == (60, 600)


def test_in_orchestrator_loop_registry() -> None:
    """Loop appears in the orchestrator's bg_loop_registry + loop_factories."""
    src = Path(__file__).parent.parent / "src" / "orchestrator.py"
    text = src.read_text()
    assert '"auto_agent_preflight"' in text
    assert "auto_agent_preflight_loop.run" in text


def test_in_service_registry() -> None:
    src = Path(__file__).parent.parent / "src" / "service_registry.py"
    text = src.read_text()
    assert "AutoAgentPreflightLoop" in text
    assert "auto_agent_preflight_loop=" in text
    assert "PreflightAuditStore" in text


def test_in_ui_constants() -> None:
    src = Path(__file__).parent.parent / "src" / "ui" / "src" / "constants.js"
    text = src.read_text()
    assert "'auto_agent_preflight'" in text
    assert "auto_agent_preflight: 120" in text
    assert "Auto-Agent Pre-Flight" in text


def test_in_scenario_catalog() -> None:
    src = Path(__file__).parent / "scenarios" / "catalog" / "loop_registrations.py"
    text = src.read_text()
    assert "_build_auto_agent_preflight" in text
    assert '"auto_agent_preflight": _build_auto_agent_preflight' in text
