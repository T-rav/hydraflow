"""PreflightAgent tests (spec §3.3, §5.1)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from preflight.agent import (
    PreflightAgentDeps,
    PreflightSpawn,
    hash_prompt,
    run_preflight,
)
from preflight.context import PreflightContext


def _ctx(sub_label: str = "flaky-test-stuck") -> PreflightContext:
    return PreflightContext(
        issue_number=42,
        issue_body="body",
        issue_comments=[],
        sub_label=sub_label,
        escalation_context=None,
        wiki_excerpts="",
        sentry_events=[],
        recent_commits=[],
    )


@pytest.mark.asyncio
async def test_resolved_response_parsed() -> None:
    spawn_fn = AsyncMock(
        return_value=PreflightSpawn(
            process=None,
            output_text="<status>resolved</status>\n<pr_url>https://x/pr/1</pr_url>\n<diagnosis>fixed it</diagnosis>",
            cost_usd=1.0,
            tokens=1000,
            crashed=False,
        )
    )
    deps = PreflightAgentDeps(
        persona="x",
        cost_cap_usd=None,
        wall_clock_cap_s=None,
        spawn_fn=spawn_fn,
    )
    out = await run_preflight(
        context=_ctx(), repo_slug="x/y", worktree_path="/tmp", deps=deps
    )
    assert out.status == "resolved"
    assert out.pr_url == "https://x/pr/1"
    assert out.diagnosis == "fixed it"


@pytest.mark.asyncio
async def test_subprocess_crash_returns_fatal() -> None:
    spawn_fn = AsyncMock(
        return_value=PreflightSpawn(
            process=None,
            output_text="partial output",
            cost_usd=0.5,
            tokens=500,
            crashed=True,
        )
    )
    deps = PreflightAgentDeps(
        persona="x",
        cost_cap_usd=None,
        wall_clock_cap_s=None,
        spawn_fn=spawn_fn,
    )
    out = await run_preflight(
        context=_ctx(), repo_slug="x/y", worktree_path="/tmp", deps=deps
    )
    assert out.status == "fatal"
    assert "Subprocess crashed" in out.diagnosis


@pytest.mark.asyncio
async def test_spawn_exception_returns_fatal() -> None:
    spawn_fn = AsyncMock(side_effect=RuntimeError("oom"))
    deps = PreflightAgentDeps(
        persona="x",
        cost_cap_usd=None,
        wall_clock_cap_s=None,
        spawn_fn=spawn_fn,
    )
    out = await run_preflight(
        context=_ctx(), repo_slug="x/y", worktree_path="/tmp", deps=deps
    )
    assert out.status == "fatal"
    assert "spawn failed" in out.diagnosis


@pytest.mark.asyncio
async def test_cost_cap_returns_cost_exceeded() -> None:
    spawn_fn = AsyncMock(
        return_value=PreflightSpawn(
            process=None,
            output_text="<status>resolved</status><diagnosis>x</diagnosis>",
            cost_usd=10.0,
            tokens=10000,
            crashed=False,
        )
    )
    deps = PreflightAgentDeps(
        persona="x",
        cost_cap_usd=5.0,
        wall_clock_cap_s=None,
        spawn_fn=spawn_fn,
    )
    out = await run_preflight(
        context=_ctx(), repo_slug="x/y", worktree_path="/tmp", deps=deps
    )
    assert out.status == "cost_exceeded"


def test_hash_prompt_stable() -> None:
    assert hash_prompt("abc") == hash_prompt("abc")
    assert hash_prompt("abc") != hash_prompt("def")
    assert hash_prompt("abc").startswith("sha256:")


@pytest.mark.asyncio
async def test_unparseable_response_falls_back_to_needs_human() -> None:
    spawn_fn = AsyncMock(
        return_value=PreflightSpawn(
            process=None,
            output_text="garbage no tags",
            cost_usd=1.0,
            tokens=100,
            crashed=False,
        )
    )
    deps = PreflightAgentDeps(
        persona="x",
        cost_cap_usd=None,
        wall_clock_cap_s=None,
        spawn_fn=spawn_fn,
    )
    out = await run_preflight(
        context=_ctx(), repo_slug="x/y", worktree_path="/tmp", deps=deps
    )
    assert out.status == "needs_human"
