"""Unit tests for the #11298 light-lane intake in AutoAgentPreflightLoop."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from auto_agent_preflight_loop import AutoAgentPreflightLoop


def _loop(config) -> AutoAgentPreflightLoop:
    loop = object.__new__(AutoAgentPreflightLoop)
    loop._config = config
    loop._prs = SimpleNamespace(list_issues_by_label=AsyncMock(return_value=[]))
    loop._state = SimpleNamespace(get_hitl_origin=lambda _n: None)
    return loop


def _config(*, light: bool, hitl: bool = False):
    return SimpleNamespace(
        auto_agent_hitl_intake_enabled=hitl,
        auto_agent_light_intake_enabled=light,
        light_autofix_label=["hydraflow-auto-light"],
        hitl_label=["hydraflow-hitl"],
        hitl_autofix_label=["hydraflow-hitl-autofix"],
        hitl_active_label=["hydraflow-hitl-active"],
    )


def _issue(number: int, *labels: str) -> dict:
    return {"number": number, "labels": [{"name": name} for name in labels]}


@pytest.mark.asyncio
async def test_light_issues_polled_and_tagged() -> None:
    loop = _loop(_config(light=True))

    async def _list(label):
        if label == "hydraflow-auto-light":
            return [_issue(9, "hydraflow-auto-light")]
        return []

    loop._prs.list_issues_by_label = AsyncMock(side_effect=_list)
    eligible = await loop._poll_eligible_issues()
    assert [i["number"] for i in eligible] == [9]
    assert eligible[0]["_intake"] == "light"


@pytest.mark.asyncio
async def test_light_poll_skipped_when_flag_off() -> None:
    loop = _loop(_config(light=False))
    calls: list[str] = []

    async def _list(label):
        calls.append(label)
        return []

    loop._prs.list_issues_by_label = AsyncMock(side_effect=_list)
    await loop._poll_eligible_issues()
    assert "hydraflow-auto-light" not in calls


@pytest.mark.asyncio
async def test_human_required_carrier_skipped() -> None:
    loop = _loop(_config(light=True))

    async def _list(label):
        if label == "hydraflow-auto-light":
            return [_issue(9, "hydraflow-auto-light", "human-required")]
        return []

    loop._prs.list_issues_by_label = AsyncMock(side_effect=_list)
    eligible = await loop._poll_eligible_issues()
    assert eligible == []
