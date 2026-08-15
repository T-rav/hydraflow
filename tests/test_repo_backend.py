"""Unit: repo-wide harness backend override — spawn routing (#11211)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import credit_failover
from config import HydraFlowConfig
from repo_backend import apply_repo_provider

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset_failover():
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


def test_noop_when_repo_provider_is_claude(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    cmd = ["claude", "--model", "claude-opus-4-8"]
    assert apply_repo_provider("claude", cmd, _cfg(tmp_path)) == ("claude", cmd)


def test_reroutes_to_zai_when_repo_provider_is_zai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    cmd = ["claude", "--model", "claude-opus-4-8", "-p", "x"]
    provider, new_cmd = apply_repo_provider(
        "claude", cmd, _cfg(tmp_path, repo_provider="zai", repo_model="glm-5.2")
    )
    assert provider == "zai"
    assert "glm-5.2" in new_cmd and "claude-opus-4-8" not in new_cmd


def test_falls_back_to_credit_failover_model_when_repo_model_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    cmd = ["claude", "--model", "claude-opus-4-8"]
    provider, new_cmd = apply_repo_provider(
        "claude", cmd, _cfg(tmp_path, repo_provider="zai")
    )
    assert provider == "zai"
    assert "glm-5.2" in new_cmd  # HydraFlowConfig.credit_failover_model default


def test_noop_when_role_already_routed_off_claude(tmp_path: Path) -> None:
    # A role-level dial (e.g. implementation_provider="zai" for this specific
    # role) that already resolved off "claude" always wins over the repo-wide
    # dial — apply_repo_provider only acts on a still-"claude" provider.
    cmd = ["claude", "--model", "some-model"]
    assert apply_repo_provider("zai", cmd, _cfg(tmp_path, repo_provider="zai")) == (
        "zai",
        cmd,
    )


def test_noop_without_zai_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Mirrors apply_credit_failover: never reroute to an endpoint with no key
    # present — that would send a glm-* model to the wrong backend.
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("HYDRAFLOW_ZAI_API_KEY", raising=False)
    cmd = ["claude", "--model", "claude-opus-4-8"]
    provider, _ = apply_repo_provider(
        "claude", cmd, _cfg(tmp_path, repo_provider="zai", repo_model="glm-5.2")
    )
    assert provider == "claude"


def test_does_not_mutate_input_cmd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "k")
    cmd = ["claude", "--model", "claude-opus-4-8"]
    apply_repo_provider("claude", cmd, _cfg(tmp_path, repo_provider="zai"))
    assert cmd == ["claude", "--model", "claude-opus-4-8"]


# --- composition with credit failover (#11211 Direction item 3) ------------


def test_repo_zai_makes_credit_failover_a_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A GLM-native repo is untouched by a process-wide Claude-cap failover.

    apply_repo_provider runs BEFORE apply_credit_failover at both spawn seams
    (base_runner._execute, BaseSubprocessRunner.run); once it has already
    rerouted a repo's spawn to "zai", apply_credit_failover's own
    `if provider != "claude"` guard short-circuits — engaging failover
    (e.g. because a *different*, Claude-native repo hit an authoritative cap)
    never touches this repo's resolved provider.
    """
    from credit_failover import apply_credit_failover

    monkeypatch.setenv("ZAI_API_KEY", "k")
    credit_failover.engage(now=NOW, resume_at=None, cooldown_minutes=15)
    cfg = _cfg(tmp_path, repo_provider="zai", repo_model="glm-5.2")
    cmd = ["claude", "--model", "claude-opus-4-8"]

    provider, cmd = apply_repo_provider("claude", cmd, cfg)
    provider, cmd = apply_credit_failover(provider, cmd, cfg)

    assert provider == "zai"
    assert cmd.count("--model") == 1
    assert "glm-5.2" in cmd


def test_claude_native_repo_still_fails_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repo left on the factory default (repo_provider unset) still fails
    over to GLM when Claude credits are exhausted — layered on top, unchanged
    from the pre-#11211 behavior."""
    from credit_failover import apply_credit_failover

    monkeypatch.setenv("ZAI_API_KEY", "k")
    credit_failover.engage(now=NOW, resume_at=None, cooldown_minutes=15)
    cfg = _cfg(tmp_path)  # repo_provider left at default "claude"
    cmd = ["claude", "--model", "claude-opus-4-8"]

    provider, cmd = apply_repo_provider("claude", cmd, cfg)
    provider, cmd = apply_credit_failover(provider, cmd, cfg)

    assert provider == "zai"
    assert "glm-5.2" in cmd
