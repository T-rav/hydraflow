"""Tests for Dependabot merge state persistence."""

from __future__ import annotations

import pytest

from config import HydraFlowConfig
from models import DependabotMergeSettings
from state import StateTracker


def test_dependabot_merge_settings_defaults():
    settings = DependabotMergeSettings()
    assert settings.authors == ["dependabot[bot]", "hydraflow-ul-bot"]
    assert settings.failure_strategy == "skip"
    assert settings.review_mode == "ci_only"


def test_dependabot_merge_settings_custom():
    settings = DependabotMergeSettings(
        authors=["dependabot[bot]", "renovate[bot]"],
        failure_strategy="hitl",
        review_mode="llm_review",
    )
    assert "renovate[bot]" in settings.authors
    assert settings.failure_strategy == "hitl"


def test_dependabot_merge_settings_validates_strategy():
    with pytest.raises(ValueError):
        DependabotMergeSettings(failure_strategy="invalid")


def test_dependabot_merge_settings_validates_review_mode():
    with pytest.raises(ValueError):
        DependabotMergeSettings(review_mode="invalid")


def test_state_tracker_dependabot_merge_settings_roundtrip(tmp_path):
    config = HydraFlowConfig(repo_root=str(tmp_path))
    state = StateTracker(config.state_file)

    settings = state.get_dependabot_merge_settings()
    assert settings.authors == ["dependabot[bot]", "hydraflow-ul-bot"]

    new_settings = DependabotMergeSettings(
        authors=["dependabot[bot]", "renovate[bot]"],
        failure_strategy="hitl",
        review_mode="llm_review",
    )
    state.set_dependabot_merge_settings(new_settings)

    loaded = state.get_dependabot_merge_settings()
    assert loaded.authors == ["dependabot[bot]", "renovate[bot]"]
    assert loaded.failure_strategy == "hitl"


def test_state_tracker_dependabot_merge_processed(tmp_path):
    config = HydraFlowConfig(repo_root=str(tmp_path))
    state = StateTracker(config.state_file)

    assert state.get_dependabot_merge_processed() == set()
    state.add_dependabot_merge_processed(42)
    state.add_dependabot_merge_processed(101)
    assert state.get_dependabot_merge_processed() == {42, 101}


def test_arch_refresh_attempts_bump_get_clear(tmp_path):
    config = HydraFlowConfig(repo_root=str(tmp_path))
    state = StateTracker(config.state_file)

    assert state.get_dependabot_arch_refresh_attempts(9422) == 0
    assert state.bump_dependabot_arch_refresh_attempts(9422) == 1
    assert state.bump_dependabot_arch_refresh_attempts(9422) == 2
    assert state.get_dependabot_arch_refresh_attempts(9422) == 2
    # An unrelated PR is independent.
    assert state.get_dependabot_arch_refresh_attempts(9423) == 0

    state.clear_dependabot_arch_refresh_attempts(9422)
    assert state.get_dependabot_arch_refresh_attempts(9422) == 0
    # Clearing an absent key is a no-op.
    state.clear_dependabot_arch_refresh_attempts(9999)


def test_arch_refresh_counter_cleared_when_pr_processed(tmp_path):
    config = HydraFlowConfig(repo_root=str(tmp_path))
    state = StateTracker(config.state_file)

    state.bump_dependabot_arch_refresh_attempts(9422)
    assert state.get_dependabot_arch_refresh_attempts(9422) == 1

    # Merging/closing/escalating the PR clears its self-heal counter so a future
    # re-stuck PR is not permanently capped.
    state.add_dependabot_merge_processed(9422)
    assert state.get_dependabot_arch_refresh_attempts(9422) == 0


def test_arch_refresh_attempts_persist_across_reload(tmp_path):
    config = HydraFlowConfig(repo_root=str(tmp_path))
    state = StateTracker(config.state_file)
    state.bump_dependabot_arch_refresh_attempts(9422)
    state.bump_dependabot_arch_refresh_attempts(9422)

    reloaded = StateTracker(config.state_file)
    assert reloaded.get_dependabot_arch_refresh_attempts(9422) == 2
