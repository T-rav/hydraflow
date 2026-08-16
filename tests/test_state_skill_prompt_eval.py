"""Tests for SkillPromptEvalStateMixin."""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def _tracker(tmp_path: Path) -> StateTracker:
    return StateTracker(state_file=tmp_path / "state.json")


def test_last_green_roundtrip(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    snap = {"case_diff_shrink_001": "PASS", "case_scope_creep_002": "PASS"}
    st.set_skill_prompt_last_green(snap)
    assert st.get_skill_prompt_last_green() == snap


def test_attempt_counter(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.get_skill_prompt_attempts("case_x") == 0
    assert st.inc_skill_prompt_attempts("case_x") == 1
    assert st.inc_skill_prompt_attempts("case_x") == 2
    st.clear_skill_prompt_attempts("case_x")
    assert st.get_skill_prompt_attempts("case_x") == 0


# --- #11280: prompt-efficiency baseline + model regime -----------------------


def test_prompt_efficiency_baseline_regime_defaults_empty(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    assert st.get_prompt_efficiency_baseline_regime() == {}


def test_prompt_efficiency_baseline_regime_roundtrip(tmp_path: Path) -> None:
    st = _tracker(tmp_path)
    totals = {"diff-sanity": {"inference_calls": 10}}
    regimes = {"diff-sanity": "glm-5.2"}
    st.set_prompt_efficiency_baseline(totals, regimes=regimes)
    assert st.get_prompt_efficiency_baseline() == totals
    assert st.get_prompt_efficiency_baseline_regime() == regimes


def test_prompt_efficiency_baseline_regime_omitted_leaves_stored_value(
    tmp_path: Path,
) -> None:
    """Omitting *regimes* must not clobber a previously-stored regime — a
    caller that doesn't track regime (or an older code path) shouldn't erase
    what a regime-aware caller already persisted."""
    st = _tracker(tmp_path)
    st.set_prompt_efficiency_baseline(
        {"diff-sanity": {"inference_calls": 10}}, regimes={"diff-sanity": "claude"}
    )
    st.set_prompt_efficiency_baseline({"diff-sanity": {"inference_calls": 20}})
    assert st.get_prompt_efficiency_baseline_regime() == {"diff-sanity": "claude"}
