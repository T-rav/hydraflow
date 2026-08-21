"""Unit: credit_failover state module + spawn routing (#10844)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import credit_failover
from config import HydraFlowConfig
from credit_failover import apply_credit_failover
from prompt_telemetry import rewrite_command_model

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    credit_failover.reset_for_tests()
    yield
    credit_failover.reset_for_tests()


def _cfg(tmp_path: Path, **over: object) -> HydraFlowConfig:
    return HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
        **over,
    )


# --- state module -----------------------------------------------------------


def test_not_active_by_default() -> None:
    assert credit_failover.is_active() is False


def test_engage_activates() -> None:
    credit_failover.engage(now=NOW, resume_at=None, cooldown_minutes=15)
    assert credit_failover.is_active() is True


def test_clear_deactivates() -> None:
    credit_failover.engage(now=NOW, resume_at=None, cooldown_minutes=15)
    credit_failover.clear()
    assert credit_failover.is_active() is False


def test_probe_after_uses_cooldown_when_no_resume_at() -> None:
    credit_failover.engage(now=NOW, resume_at=None, cooldown_minutes=15)
    assert credit_failover.status().probe_after == NOW + timedelta(minutes=15)


def test_probe_after_uses_resume_at_when_future() -> None:
    resume = NOW + timedelta(hours=3)
    credit_failover.engage(now=NOW, resume_at=resume, cooldown_minutes=15)
    assert credit_failover.status().probe_after == resume


def test_probe_after_falls_back_to_cooldown_when_resume_at_past() -> None:
    resume = NOW - timedelta(hours=1)
    credit_failover.engage(now=NOW, resume_at=resume, cooldown_minutes=15)
    assert credit_failover.status().probe_after == NOW + timedelta(minutes=15)


def test_probe_due_false_before_probe_after() -> None:
    credit_failover.engage(now=NOW, resume_at=None, cooldown_minutes=15)
    assert credit_failover.probe_due(NOW) is False


def test_probe_due_true_at_or_after_probe_after() -> None:
    credit_failover.engage(now=NOW, resume_at=None, cooldown_minutes=15)
    assert credit_failover.probe_due(NOW + timedelta(minutes=16)) is True


def test_probe_due_false_when_not_active() -> None:
    assert credit_failover.probe_due(NOW + timedelta(days=1)) is False


def test_advance_probe_pushes_probe_after() -> None:
    credit_failover.engage(now=NOW, resume_at=None, cooldown_minutes=15)
    later = NOW + timedelta(minutes=20)
    credit_failover.advance_probe(now=later, cooldown_minutes=15)
    assert credit_failover.status().probe_after == later + timedelta(minutes=15)


# --- rewrite_command_model --------------------------------------------------


def test_rewrite_replaces_existing_model() -> None:
    cmd = ["claude", "--model", "claude-opus-4-8", "-p", "prompt"]
    assert rewrite_command_model(cmd, "glm-5.2") == [
        "claude",
        "--model",
        "glm-5.2",
        "-p",
        "prompt",
    ]


def test_rewrite_appends_when_absent() -> None:
    cmd = ["claude", "-p", "prompt"]
    assert rewrite_command_model(cmd, "glm-5.2") == [
        "claude",
        "-p",
        "prompt",
        "--model",
        "glm-5.2",
    ]


def test_rewrite_does_not_mutate_input() -> None:
    cmd = ["claude", "--model", "x"]
    rewrite_command_model(cmd, "glm-5.2")
    assert cmd == ["claude", "--model", "x"]


# --- apply_credit_failover --------------------------------------------------


def test_apply_noop_when_not_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    cmd = ["claude", "--model", "claude-opus-4-8"]
    assert apply_credit_failover("claude", cmd, _cfg(tmp_path)) == ("claude", cmd)


def test_apply_reroutes_to_zai_glm_when_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    credit_failover.engage(now=NOW, resume_at=None, cooldown_minutes=15)
    cmd = ["claude", "--model", "claude-opus-4-8", "-p", "x"]
    provider, new_cmd = apply_credit_failover("claude", cmd, _cfg(tmp_path))
    assert provider == "zai"
    assert "glm-5.2" in new_cmd and "claude-opus-4-8" not in new_cmd


def test_gateway_failover_keeps_transport_and_needs_no_real_zai_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_CODING_PLAN_KEY", raising=False)
    credit_failover.engage(now=NOW, resume_at=None, cooldown_minutes=15)
    cmd = ["claude", "--model", "claude-opus-4-8", "-p", "x"]

    provider, new_cmd = apply_credit_failover("gateway", cmd, _cfg(tmp_path))

    assert provider == "gateway"
    assert "glm-5.2" in new_cmd and "claude-opus-4-8" not in new_cmd


def test_apply_noop_when_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    credit_failover.engage(now=NOW, resume_at=None, cooldown_minutes=15)
    cmd = ["claude", "--model", "claude-opus-4-8"]
    provider, _ = apply_credit_failover(
        "claude", cmd, _cfg(tmp_path, credit_failover_enabled=False)
    )
    assert provider == "claude"


def test_apply_noop_without_zai_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("HYDRAFLOW_ZAI_API_KEY", raising=False)
    credit_failover.engage(now=NOW, resume_at=None, cooldown_minutes=15)
    cmd = ["claude", "--model", "claude-opus-4-8"]
    provider, _ = apply_credit_failover("claude", cmd, _cfg(tmp_path))
    assert provider == "claude"


def test_apply_leaves_non_claude_provider_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    credit_failover.engage(now=NOW, resume_at=None, cooldown_minutes=15)
    cmd = ["claude", "--model", "glm-5.2"]
    assert apply_credit_failover("zai", cmd, _cfg(tmp_path)) == ("zai", cmd)
