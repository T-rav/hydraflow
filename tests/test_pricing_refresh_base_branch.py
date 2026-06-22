"""PricingRefreshLoop must target config.base_branch(), not a hardcoded main.

Regression for the main-targeted-PR runaway (mirrors
test_diagram_loop.test_regen_pr_uses_config_base_branch_staging). The pricing
refresh PR previously hardcoded ``base="main"``; under ADR-0042 that PR is
BLOCKED by branch protection and never merges.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from pricing_refresh_diff import PricingDiff
from pricing_refresh_loop import PricingRefreshLoop


@pytest.mark.asyncio
async def test_refresh_pr_uses_config_base_branch_staging(
    tmp_path: Path, monkeypatch
) -> None:
    config = MagicMock()
    config.pricing_refresh_loop_enabled = True
    config.base_branch.return_value = "staging"

    deps = LoopDeps(
        event_bus=MagicMock(),
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=MagicMock(return_value=True),
        sleep_fn=AsyncMock(),
        interval_cb=MagicMock(return_value=86400),
    )
    loop = PricingRefreshLoop(config=config, pr_manager=MagicMock(), deps=deps)
    loop._set_repo_root(tmp_path)

    captured: dict = {}

    import auto_pr as _auto_pr_mod

    async def intercept(**kw):
        captured["base"] = kw["base"]
        from auto_pr import AutoPrResult

        return AutoPrResult(
            status="opened",
            pr_url="https://github.com/T-rav/hydraflow/pull/1",
            branch=kw["branch"],
            error=None,
        )

    monkeypatch.setattr(_auto_pr_mod, "generate_and_open_pr_async", intercept)

    diff = PricingDiff(updated={"claude-opus": {"input_cost_per_token": 1.0}})
    await loop._open_or_update_refresh_pr(diff)

    assert captured["base"] == "staging"
