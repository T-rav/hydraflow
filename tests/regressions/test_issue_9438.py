"""Regression for issue #9438.

``ContractRefreshLoop._record_all`` hardcodes the module constant
``_SANDBOX_GITHUB_REPO`` when invoking the GitHub recorder instead of
resolving the sandbox slug from ``self._config.contracts_sandbox_repo``.

``config.contracts_sandbox_repo`` documents itself as the override point
("Override if the sandbox org is renamed"), but the loop ignores it, so
renaming the sandbox org in config silently has no effect — latent config
drift. This test overrides ``contracts_sandbox_repo`` to a non-default slug
and asserts the recorder is invoked with that override. It is RED until the
loop reads the config field.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import contract_refresh_loop as crl_module
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from contract_refresh_loop import ContractRefreshLoop
from events import EventBus
from state import StateTracker

_OVERRIDE_SANDBOX_REPO = "RenamedOrg/renamed-contracts-sandbox"


class _FakeState:
    """Minimal StateTracker stand-in: contract-refresh attempt counters only."""

    def __init__(self) -> None:
        self._attempts: dict[str, int] = {}

    def get_contract_refresh_attempts(self, adapter: str) -> int:
        return int(self._attempts.get(adapter, 0))

    def inc_contract_refresh_attempts(self, adapter: str) -> int:
        self._attempts[adapter] = self._attempts.get(adapter, 0) + 1
        return self._attempts[adapter]

    def clear_contract_refresh_attempts(self, adapter: str) -> None:
        self._attempts.pop(adapter, None)


def _build_loop(tmp_path: Path) -> ContractRefreshLoop:
    cfg = HydraFlowConfig(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        repo="hydra/hydraflow",
        contracts_sandbox_repo=_OVERRIDE_SANDBOX_REPO,
        contract_refresh_external_enabled=True,
    )
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )
    return ContractRefreshLoop(
        config=cfg,
        prs=AsyncMock(),
        state=cast(StateTracker, _FakeState()),
        deps=deps,
    )


def test_record_all_uses_config_sandbox_repo_override(
    tmp_path: Path, monkeypatch: Any
) -> None:
    captured_sandbox_repos: list[str] = []

    def _capturing_record_github(sandbox_repo: str, _tmp_dir: Path) -> list[Path]:
        captured_sandbox_repos.append(sandbox_repo)
        return []

    monkeypatch.setattr(crl_module, "record_github", _capturing_record_github)
    monkeypatch.setattr(crl_module, "record_git", lambda *_a, **_k: [])
    monkeypatch.setattr(crl_module, "record_docker", lambda *_a, **_k: [])
    monkeypatch.setattr(crl_module, "record_claude_stream", lambda *_a, **_k: [])

    loop = _build_loop(tmp_path)
    tmp_root = tmp_path / "recordings"
    tmp_root.mkdir(parents=True, exist_ok=True)

    asyncio.run(loop._record_all(tmp_root))

    assert captured_sandbox_repos == [_OVERRIDE_SANDBOX_REPO], (
        "record_github was invoked with "
        f"{captured_sandbox_repos!r}, but the loop should resolve the sandbox "
        f"slug from config.contracts_sandbox_repo ({_OVERRIDE_SANDBOX_REPO!r}). "
        "The loop hardcodes _SANDBOX_GITHUB_REPO so the documented config "
        "override silently has no effect (issue #9438)."
    )
