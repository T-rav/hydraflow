"""Regression tests for #9719 — escalation TTL re-drive state + config.

Fix B2 of the dark-factory hardening roadmap: auto-agent-exhausted
escalations whose gap is still real sat in ``human-required`` forever
(#9618 sat six days). The re-drive marker (``StateData.auto_agent_redrive``)
tracks the exhaustion transition so ``AutoAgentPreflightLoop`` can re-feed
the issue to preflight after a TTL.

The load-bearing guard here is idempotent arming: re-running the exhaustion
branch on a later tick must NOT refresh ``exhausted_at``, or the marker
never ages and re-drive never fires (the #9716 restart-once marker lesson).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from config import HydraFlowConfig  # noqa: E402
from state import StateTracker  # noqa: E402


def _tracker(tmp_path: Path) -> StateTracker:
    return StateTracker(state_file=tmp_path / "state.json")


# ---------------------------------------------------------------------------
# Marker state mixin
# ---------------------------------------------------------------------------


def test_arm_then_list_returns_armed_marker(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    st.arm_auto_agent_redrive(9618, "2026-07-01T00:00:00Z")
    assert st.list_armed_auto_agent_redrives() == [(9618, "2026-07-01T00:00:00Z", 0)]


def test_arming_already_armed_marker_preserves_first_timestamp(
    tmp_path: Path,
) -> None:
    # The re-arm trap (#9716): the exhaustion branch re-runs on every
    # re-confirmation tick; a blind ``exhausted_at = now`` would keep the
    # marker forever young and re-drive would never fire.
    st = _tracker(tmp_path)
    st.arm_auto_agent_redrive(9618, "2026-07-01T00:00:00Z")
    st.arm_auto_agent_redrive(9618, "2026-07-09T00:00:00Z")
    assert st.list_armed_auto_agent_redrives() == [(9618, "2026-07-01T00:00:00Z", 0)]


def test_record_redrive_disarms_and_increments(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    st.arm_auto_agent_redrive(9618, "2026-07-01T00:00:00Z")
    assert st.record_auto_agent_redrive(9618) == 1
    assert st.list_armed_auto_agent_redrives() == []
    assert st.get_auto_agent_redrive_count(9618) == 1


def test_rearm_after_redrive_sets_fresh_timestamp_keeps_count(
    tmp_path: Path,
) -> None:
    # Each backoff window measures from its OWN exhaustion transition.
    st = _tracker(tmp_path)
    st.arm_auto_agent_redrive(9618, "2026-07-01T00:00:00Z")
    st.record_auto_agent_redrive(9618)
    st.arm_auto_agent_redrive(9618, "2026-07-12T00:00:00Z")
    assert st.list_armed_auto_agent_redrives() == [(9618, "2026-07-12T00:00:00Z", 1)]
    assert st.get_auto_agent_redrive_count(9618) == 1


def test_clear_removes_record(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    st.arm_auto_agent_redrive(9618, "2026-07-01T00:00:00Z")
    st.record_auto_agent_redrive(9618)
    st.clear_auto_agent_redrive(9618)
    assert st.list_armed_auto_agent_redrives() == []
    assert st.get_auto_agent_redrive_count(9618) == 0


def test_clear_unknown_issue_is_noop(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    st.clear_auto_agent_redrive(424242)  # must not raise
    assert st.get_auto_agent_redrive_count(424242) == 0


def test_marker_survives_tracker_reload(tmp_path: Path) -> None:
    st1 = _tracker(tmp_path)
    st1.arm_auto_agent_redrive(9618, "2026-07-01T00:00:00Z")
    st1.record_auto_agent_redrive(7000)

    st2 = _tracker(tmp_path)
    assert st2.list_armed_auto_agent_redrives() == [(9618, "2026-07-01T00:00:00Z", 0)]
    assert st2.get_auto_agent_redrive_count(7000) == 1


def test_old_state_json_without_field_loads_clean(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"convergence_ledgers": {}}))
    st = StateTracker(state_file=state_file)
    assert st.list_armed_auto_agent_redrives() == []
    assert st.get_auto_agent_redrive_count(9618) == 0


# ---------------------------------------------------------------------------
# Config knobs
# ---------------------------------------------------------------------------


def test_redrive_config_defaults() -> None:
    c = HydraFlowConfig()
    assert c.auto_agent_redrive_enabled is True
    assert c.auto_agent_redrive_max_attempts == 1
    assert c.auto_agent_redrive_ttl_days == 5
    assert c.auto_agent_redrive_backoff_multiplier == 3.0
    assert c.auto_agent_redrive_human_quiet_days == 2


def test_redrive_ttl_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYDRAFLOW_AUTO_AGENT_REDRIVE_TTL_DAYS", "10")
    c = HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
    )
    assert c.auto_agent_redrive_ttl_days == 10


def test_redrive_enabled_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYDRAFLOW_AUTO_AGENT_REDRIVE_ENABLED", "false")
    c = HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
    )
    assert c.auto_agent_redrive_enabled is False


def test_redrive_bounds_enforced() -> None:
    with pytest.raises(ValidationError):
        HydraFlowConfig(auto_agent_redrive_ttl_days=0)
    with pytest.raises(ValidationError):
        HydraFlowConfig(auto_agent_redrive_max_attempts=-1)
    with pytest.raises(ValidationError):
        HydraFlowConfig(auto_agent_redrive_backoff_multiplier=0.5)
