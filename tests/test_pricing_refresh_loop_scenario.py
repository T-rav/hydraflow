"""PricingRefreshLoop _do_work tests with mocked seams."""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pricing_refresh_loop import PricingRefreshLoop


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """Worktree-style root with a populated model_pricing.json."""
    pricing_path = tmp_path / "src" / "assets" / "model_pricing.json"
    pricing_path.parent.mkdir(parents=True)
    pricing_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "currency": "USD",
                "updated_at": "2026-04-01",
                "source": "https://docs.anthropic.com/en/docs/about-claude/models",
                "models": {
                    "claude-haiku-4-5-20251001": {
                        "provider": "anthropic",
                        "aliases": ["haiku"],
                        "input_cost_per_million": 1.00,
                        "output_cost_per_million": 5.00,
                        "cache_write_cost_per_million": 1.25,
                        "cache_read_cost_per_million": 0.10,
                    },
                },
            },
            indent=2,
        )
        + "\n"
    )
    return tmp_path


def _build_loop(repo_root: Path) -> tuple[PricingRefreshLoop, AsyncMock]:
    pr_manager = AsyncMock(
        find_existing_issue=AsyncMock(return_value=0),
        create_issue=AsyncMock(return_value=0),
    )
    deps = MagicMock()
    config = MagicMock()
    loop = PricingRefreshLoop(config=config, pr_manager=pr_manager, deps=deps)
    loop._set_repo_root(repo_root)
    return loop, pr_manager


async def test_no_drift_returns_drift_false(repo_root: Path) -> None:
    """Upstream matches local exactly → no PR opened, no issue."""
    upstream_payload = {
        "claude-haiku-4-5-20251001": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 1e-6,
            "output_cost_per_token": 5e-6,
            "cache_creation_input_token_cost": 1.25e-6,
            "cache_read_input_token_cost": 1e-7,
        },
    }
    loop, pr_manager = _build_loop(repo_root)

    pr_helper = AsyncMock()
    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            return_value=upstream_payload,
        ),
        patch("auto_pr.generate_and_open_pr_async", pr_helper),
    ):
        result = await loop._do_work()

    assert result == {"drift": False}
    pr_helper.assert_not_awaited()
    pr_manager.create_issue.assert_not_awaited()


async def test_drift_opens_pr_via_auto_pr(repo_root: Path) -> None:
    """Upstream price differs → PR opened on pricing-refresh-auto branch."""
    upstream_payload = {
        "claude-haiku-4-5-20251001": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 1.5e-6,  # was 1.0/M, now 1.5/M (+50%, within bounds)
            "output_cost_per_token": 5e-6,
            "cache_creation_input_token_cost": 1.25e-6,
            "cache_read_input_token_cost": 1e-7,
        },
    }
    loop, pr_manager = _build_loop(repo_root)

    pr_result = MagicMock(
        status="opened", pr_url="https://github.com/x/y/pull/1", error=None
    )
    pr_helper = AsyncMock(return_value=pr_result)

    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            return_value=upstream_payload,
        ),
        patch("auto_pr.generate_and_open_pr_async", pr_helper),
    ):
        result = await loop._do_work()

    assert result["drift"] is True
    assert result["updated"] == 1
    assert result["pr_url"] == "https://github.com/x/y/pull/1"
    pr_helper.assert_awaited_once()
    kwargs = pr_helper.await_args.kwargs
    assert kwargs["branch"] == "pricing-refresh-auto"
    assert kwargs["pr_title"].startswith("chore(pricing): refresh from LiteLLM")
    assert kwargs["auto_merge"] is False
    assert "hydraflow-ready" in kwargs["labels"]
    # Generate-in-worktree (#9539): targeted path spec + a generate callable,
    # no repo_root file copy.
    assert kwargs["path_specs"] == ["src/assets/model_pricing.json"]
    assert callable(kwargs["generate"])


async def test_drift_leaves_repo_root_clean_and_generates_into_worktree(
    repo_root: Path, tmp_path: Path
) -> None:
    """#9539: repo_root is NEVER written; the proposed file is generated INTO
    the worktree by the supplied ``generate`` callback.

    The PR primitive is mocked, so the loop never touches ``repo_root``. We
    then run the captured ``generate`` callback against a separate worktree
    seeded with the same baseline and assert the new value lands there.
    """
    upstream_payload = {
        "claude-haiku-4-5-20251001": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 1.5e-6,
            "output_cost_per_token": 5e-6,
            "cache_creation_input_token_cost": 1.25e-6,
            "cache_read_input_token_cost": 1e-7,
        },
    }
    loop, _ = _build_loop(repo_root)
    before = (repo_root / "src" / "assets" / "model_pricing.json").read_text()

    pr_result = MagicMock(status="opened", pr_url="x", error=None)
    pr_helper = AsyncMock(return_value=pr_result)
    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            return_value=upstream_payload,
        ),
        patch("auto_pr.generate_and_open_pr_async", pr_helper),
    ):
        await loop._do_work()

    # repo_root stays byte-identical — nothing under it was written.
    after = (repo_root / "src" / "assets" / "model_pricing.json").read_text()
    assert after == before

    # Run the captured generate callback against a fresh worktree seeded with
    # the baseline and confirm the proposed value lands there.
    generate = pr_helper.await_args.kwargs["generate"]
    worktree = tmp_path / "wt"
    wt_pricing = worktree / "src" / "assets" / "model_pricing.json"
    wt_pricing.parent.mkdir(parents=True)
    wt_pricing.write_text(before)
    await generate(worktree)

    on_disk = json.loads(wt_pricing.read_text())
    assert (
        on_disk["models"]["claude-haiku-4-5-20251001"]["input_cost_per_million"] == 1.5
    )
    assert on_disk["updated_at"] != "2026-04-01"  # bumped


async def test_added_model_generates_into_worktree(
    repo_root: Path, tmp_path: Path
) -> None:
    """An upstream-only model is added to the worktree JSON with provider+aliases."""
    upstream_payload = {
        "claude-haiku-4-5-20251001": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 1e-6,
            "output_cost_per_token": 5e-6,
            "cache_creation_input_token_cost": 1.25e-6,
            "cache_read_input_token_cost": 1e-7,
        },
        "claude-future-99": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 2e-6,
            "output_cost_per_token": 10e-6,
        },
    }
    loop, _ = _build_loop(repo_root)
    before = (repo_root / "src" / "assets" / "model_pricing.json").read_text()

    pr_result = MagicMock(status="opened", pr_url="x", error=None)
    pr_helper = AsyncMock(return_value=pr_result)
    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            return_value=upstream_payload,
        ),
        patch("auto_pr.generate_and_open_pr_async", pr_helper),
    ):
        result = await loop._do_work()

    # repo_root untouched (#9539).
    assert (repo_root / "src" / "assets" / "model_pricing.json").read_text() == before

    generate = pr_helper.await_args.kwargs["generate"]
    worktree = tmp_path / "wt"
    wt_pricing = worktree / "src" / "assets" / "model_pricing.json"
    wt_pricing.parent.mkdir(parents=True)
    wt_pricing.write_text(before)
    await generate(worktree)

    on_disk = json.loads(wt_pricing.read_text())
    assert "claude-future-99" in on_disk["models"]
    new_entry = on_disk["models"]["claude-future-99"]
    assert new_entry["provider"] == "anthropic"
    assert new_entry["aliases"] == []
    assert new_entry["input_cost_per_million"] == 2.0
    assert result["added"] == 1


async def test_network_error_returns_no_drift_no_issue(repo_root: Path) -> None:
    """Transient network outage: log + skip, never spam an issue."""
    loop, pr_manager = _build_loop(repo_root)
    pr_helper = AsyncMock()

    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            side_effect=urllib.error.URLError("connection refused"),
        ),
        patch("auto_pr.generate_and_open_pr_async", pr_helper),
    ):
        result = await loop._do_work()

    assert result == {"drift": False, "error": "network"}
    pr_helper.assert_not_awaited()
    pr_manager.create_issue.assert_not_awaited()


async def test_bounds_violation_opens_issue_no_pr(repo_root: Path) -> None:
    """A doubled price triggers issue + no PR + no file write."""
    upstream_payload = {
        "claude-haiku-4-5-20251001": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 3e-6,  # was 1/M, now 3/M = +200%, REJECT
            "output_cost_per_token": 5e-6,
            "cache_creation_input_token_cost": 1.25e-6,
            "cache_read_input_token_cost": 1e-7,
        },
    }
    loop, pr_manager = _build_loop(repo_root)
    pr_helper = AsyncMock()

    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            return_value=upstream_payload,
        ),
        patch("auto_pr.generate_and_open_pr_async", pr_helper),
    ):
        result = await loop._do_work()

    assert result["error"] == "bounds"
    assert result["violations"] == 1
    pr_helper.assert_not_awaited()
    pr_manager.create_issue.assert_awaited_once()
    issue_kwargs = pr_manager.create_issue.await_args.kwargs
    assert issue_kwargs["title"].startswith("[pricing-refresh]")
    assert "hydraflow-find" in issue_kwargs["labels"]
    assert "claude-haiku-4-5-20251001" in issue_kwargs["body"]


async def test_bounds_violation_does_not_overwrite_pricing_file(
    repo_root: Path,
) -> None:
    """The on-disk file must NOT be touched when a bounds guard fires."""
    upstream_payload = {
        "claude-haiku-4-5-20251001": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 3e-6,
            "output_cost_per_token": 5e-6,
            "cache_creation_input_token_cost": 1.25e-6,
            "cache_read_input_token_cost": 1e-7,
        },
    }
    loop, _ = _build_loop(repo_root)
    pricing_path = repo_root / "src" / "assets" / "model_pricing.json"
    before = pricing_path.read_text()

    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            return_value=upstream_payload,
        ),
        patch("auto_pr.generate_and_open_pr_async", AsyncMock()),
    ):
        await loop._do_work()

    after = pricing_path.read_text()
    assert before == after


async def test_bounds_issue_dedups_by_title_prefix(repo_root: Path) -> None:
    """If an open bounds-violation issue already exists, do not file a duplicate."""
    upstream_payload = {
        "claude-haiku-4-5-20251001": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 3e-6,
            "output_cost_per_token": 5e-6,
            "cache_creation_input_token_cost": 1.25e-6,
            "cache_read_input_token_cost": 1e-7,
        },
    }
    loop, pr_manager = _build_loop(repo_root)
    pr_manager.find_existing_issue = AsyncMock(return_value=42)  # already open

    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            return_value=upstream_payload,
        ),
        patch("auto_pr.generate_and_open_pr_async", AsyncMock()),
    ):
        await loop._do_work()

    pr_manager.create_issue.assert_not_awaited()


async def test_kill_switch_short_circuits(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HYDRAFLOW_DISABLE_PRICING_REFRESH=1 → return immediately."""
    monkeypatch.setenv("HYDRAFLOW_DISABLE_PRICING_REFRESH", "1")
    loop, pr_manager = _build_loop(repo_root)
    fetch = AsyncMock()
    pr_helper = AsyncMock()

    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            fetch,
        ),
        patch("auto_pr.generate_and_open_pr_async", pr_helper),
    ):
        result = await loop._do_work()

    assert result == {"skipped": "kill_switch"}
    fetch.assert_not_called()
    pr_helper.assert_not_awaited()
    pr_manager.create_issue.assert_not_awaited()


async def test_parse_error_opens_deduped_issue(repo_root: Path) -> None:
    """Upstream returns non-JSON → parse-error issue, no PR, no file change."""
    loop, pr_manager = _build_loop(repo_root)
    pr_helper = AsyncMock()
    pricing_path = repo_root / "src" / "assets" / "model_pricing.json"
    before = pricing_path.read_text()

    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            side_effect=json.JSONDecodeError("Expecting value", "", 0),
        ),
        patch("auto_pr.generate_and_open_pr_async", pr_helper),
    ):
        result = await loop._do_work()

    assert result == {"drift": False, "error": "parse"}
    pr_helper.assert_not_awaited()
    pr_manager.create_issue.assert_awaited_once()
    issue_kwargs = pr_manager.create_issue.await_args.kwargs
    assert issue_kwargs["title"] == "[pricing-refresh] upstream parse error"
    assert "hydraflow-find" in issue_kwargs["labels"]
    assert pricing_path.read_text() == before


async def test_parse_error_dedups_when_issue_already_open(repo_root: Path) -> None:
    """Already-open parse-error issue → no duplicate."""
    loop, pr_manager = _build_loop(repo_root)
    pr_manager.find_existing_issue = AsyncMock(return_value=99)

    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            side_effect=json.JSONDecodeError("bad", "", 0),
        ),
        patch("auto_pr.generate_and_open_pr_async", AsyncMock()),
    ):
        await loop._do_work()

    pr_manager.create_issue.assert_not_awaited()


async def test_pr_failure_returns_pr_failed_and_leaves_repo_root_clean(
    repo_root: Path,
) -> None:
    """#9539: a failed PR-open returns ``pr_failed`` and never mutates repo_root.

    There is no revert path anymore — the proposed file was only ever written
    into the (now-torn-down) worktree, so ``repo_root`` is untouched whether
    the PR opened or failed.
    """
    upstream_payload = {
        "claude-haiku-4-5-20251001": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 1.5e-6,  # +50%, within bounds
            "output_cost_per_token": 5e-6,
            "cache_creation_input_token_cost": 1.25e-6,
            "cache_read_input_token_cost": 1e-7,
        },
    }
    loop, _ = _build_loop(repo_root)
    pricing_path = repo_root / "src" / "assets" / "model_pricing.json"
    before = pricing_path.read_text()

    pr_result = MagicMock(status="failed", pr_url=None, error="boom")
    pr_helper = AsyncMock(return_value=pr_result)

    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            return_value=upstream_payload,
        ),
        patch("auto_pr.generate_and_open_pr_async", pr_helper),
    ):
        result = await loop._do_work()

    assert result["error"] == "pr_failed"
    assert result["pr_url"] is None
    # repo_root is byte-identical — the proposal lived only in the worktree.
    assert pricing_path.read_text() == before


async def test_clean_tick_closes_open_pricing_issues(repo_root: Path) -> None:
    """#9359: a clean parse + no bounds violations auto-closes any open
    `[pricing-refresh]` parse-error / bounds-violation issues."""
    upstream_payload = {
        "claude-haiku-4-5-20251001": {
            "litellm_provider": "anthropic",
            "input_cost_per_token": 1e-6,
            "output_cost_per_token": 5e-6,
            "cache_creation_input_token_cost": 1.25e-6,
            "cache_read_input_token_cost": 1e-7,
        },
    }
    loop, pr_manager = _build_loop(repo_root)
    pr_manager.find_existing_issue = AsyncMock(return_value=88)  # both "open"

    pr_helper = AsyncMock()
    with (
        patch(
            "pricing_refresh_loop.PricingRefreshLoop._fetch_upstream",
            return_value=upstream_payload,
        ),
        patch("auto_pr.generate_and_open_pr_async", pr_helper),
    ):
        result = await loop._do_work()

    assert result == {"drift": False}
    # Parse-error AND bounds-violation issues both auto-close on a clean tick.
    assert pr_manager.close_issue.await_count == 2
    assert {c.args[0] for c in pr_manager.close_issue.await_args_list} == {88}
