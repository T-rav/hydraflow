"""Tests for FakeCoverageAuditorLoop (spec §4.7)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from fake_coverage_auditor_loop import (
    FakeCoverageAuditorLoop,
    catalog_cassette_methods,
    catalog_fake_methods,
)


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(
        data_root=tmp_path, repo="hydra/hydraflow", repo_root=tmp_path
    )
    state = MagicMock()
    state.get_fake_coverage_last_known.return_value = {}
    state.get_fake_coverage_attempts.return_value = 0
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()
    return cfg, state, pr, dedup


def test_skeleton_worker_name_and_interval(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = FakeCoverageAuditorLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )
    assert loop._worker_name == "fake_coverage_auditor"
    assert loop._get_default_interval() == 604800


def test_catalog_fake_methods_splits_surface_vs_helper(tmp_path: Path) -> None:
    fake_dir = tmp_path / "fakes"
    fake_dir.mkdir()
    (fake_dir / "fake_github.py").write_text(
        "from dataclasses import dataclass\n\n"
        "class FakeGitHub:\n"
        "    async def create_issue(self, title, body, labels): ...\n"
        "    async def close_issue(self, num): ...\n"
        "    def script_ci(self, events): ...\n"
        "    def fail_service(self, reason): ...\n"
        "    def _private(self): ...\n"
    )

    cat = catalog_fake_methods(fake_dir)
    assert "FakeGitHub" in cat
    surface = set(cat["FakeGitHub"]["adapter-surface"])
    helpers = set(cat["FakeGitHub"]["test-helper"])
    assert surface == {"create_issue", "close_issue"}
    assert helpers == {"script_ci", "fail_service"}


def test_catalog_cassette_methods_reads_input_command(tmp_path: Path) -> None:
    import yaml

    cassettes = tmp_path / "cassettes" / "github"
    cassettes.mkdir(parents=True)
    (cassettes / "create_issue.yaml").write_text(
        yaml.safe_dump({"input": {"command": "create_issue"}, "output": {}})
    )
    (cassettes / "close_issue.yaml").write_text(
        yaml.safe_dump({"input": {"command": "close_issue"}, "output": {}})
    )
    methods = catalog_cassette_methods(cassettes)
    assert methods == {"create_issue", "close_issue"}
