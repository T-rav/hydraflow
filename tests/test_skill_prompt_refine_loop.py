"""Config knobs + weekly-cap state for prompt-refinement (#9724)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def test_refine_config_defaults() -> None:
    from config import HydraFlowConfig

    cfg = HydraFlowConfig()
    assert cfg.skill_prompt_refine_enabled is True
    assert cfg.skill_prompt_refine_max_weekly == 2
    assert cfg.skill_prompt_refine_model == ""


def test_weekly_cap_state_prunes(tmp_path) -> None:
    from state import StateTracker

    st = StateTracker(state_file=tmp_path / "state.json")
    now = datetime.now(UTC)
    st.record_refine_proposal((now - timedelta(days=8)).isoformat())
    st.record_refine_proposal(now.isoformat())
    assert st.refine_proposals_last_7d(now) == 1
