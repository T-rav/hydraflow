"""Regression pins for the two review findings on PR #12043 (#12040).

1. Provider dials are Literal["claude", "gateway", "zai"] — the first cut of
   ``_check_docker_agent_credential`` collapsed zai into claude, hard-FAILing
   a valid GLM config (ZAI_API_KEY set, no Anthropic credential) at boot with
   the wrong remedy ("claude setup-token").
2. It read .env with ``config._dotenv_lookup`` while the container env is
   built with ``subprocess_util._read_dotenv`` — divergent parsers meant an
   ``export KEY=...`` line the container can never see satisfied preflight,
   recreating the exact mid-run auth failure the check exists to prevent.

These pins are deliberately thin: the behavioural matrix lives in
``tests/test_preflight.py``; this file exists so the two shipped-then-caught
defects can never quietly return.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from preflight import CheckStatus, _check_docker_agent_credential
from tests.helpers import config_mock

_CREDENTIAL_KEYS = (
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ZAI_CODING_PLAN_KEY",
    "HYDRAFLOW_ZAI_CODING_PLAN_KEY",
    "ZAI_API_KEY",
    "HYDRAFLOW_ZAI_API_KEY",
)


def _zai_config(tmp_path: Path) -> object:
    config = config_mock()
    config.repo_root = tmp_path
    config.implementation_tool = "claude"
    config.review_tool = "claude"
    config.planner_tool = "claude"
    config.implementation_provider = "zai"
    config.review_provider = "zai"
    config.planner_provider = "zai"
    return config


def test_zai_config_with_zai_key_is_not_blocked_at_boot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in _CREDENTIAL_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ZAI_API_KEY", "zai-live")
    result = _check_docker_agent_credential(_zai_config(tmp_path))
    assert result.status == CheckStatus.PASS
    assert "setup-token" not in result.message


def test_export_prefixed_dotenv_token_does_not_satisfy_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in _CREDENTIAL_KEYS:
        monkeypatch.delenv(key, raising=False)
    config = config_mock()
    config.repo_root = tmp_path
    config.implementation_tool = "claude"
    config.review_tool = "codex"
    config.planner_tool = "codex"
    config.implementation_provider = "claude"
    (tmp_path / ".env").write_text(
        "export CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-container-never-sees-this\n",
        encoding="utf-8",
    )
    result = _check_docker_agent_credential(config)
    assert result.status == CheckStatus.FAIL, (
        "make_docker_env's parser cannot read export-prefixed lines, so the "
        "container never receives this token — preflight must agree"
    )
