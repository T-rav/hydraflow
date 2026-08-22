"""Tests for the PR auto-rebase actuator (#11595 option 3).

Pure decision core (``decide_autorebase``) plus the ``PRAutoRebase``
executor: dirty + own-PR + not-yet-tried-at-this-staging-head → one
merge+regen+push attempt via the existing arch-refresh engine;
source-conflict → abort + one surfaced comment; dedup persisted BEFORE the
attempt so a crash cannot loop.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from auto_pr import ArchRefreshResult
from dedup_store import DedupStore
from merge_state_watcher import ConflictingPR
from pr_autorebase import PRAutoRebase, decide_autorebase, is_factory_branch
from tests.helpers import ConfigFactory

if TYPE_CHECKING:
    from typing import Any

_SHA = "a" * 40
_OTHER_SHA = "b" * 40


# ---------------------------------------------------------------------------
# Pure decision core
# ---------------------------------------------------------------------------


def test_decide_attempts_fresh_factory_pr_at_new_head() -> None:
    decision = decide_autorebase(
        enabled=True,
        branch="agent/issue-11595",
        pr_number=42,
        staging_sha=_SHA,
        attempted=set(),
    )
    assert decision.action == "attempt"
    assert decision.dedup_key == f"42@{_SHA}"


def test_decide_skips_when_disabled() -> None:
    decision = decide_autorebase(
        enabled=False,
        branch="agent/issue-11595",
        pr_number=42,
        staging_sha=_SHA,
        attempted=set(),
    )
    assert decision.action == "skipped_disabled"


def test_decide_skips_non_factory_branch() -> None:
    decision = decide_autorebase(
        enabled=True,
        branch="feat/operator-work",
        pr_number=42,
        staging_sha=_SHA,
        attempted=set(),
    )
    assert decision.action == "skipped_not_factory"


def test_decide_skips_when_staging_sha_unknown() -> None:
    decision = decide_autorebase(
        enabled=True,
        branch="agent/issue-11595",
        pr_number=42,
        staging_sha="",
        attempted=set(),
    )
    assert decision.action == "skipped_no_staging_sha"


def test_decide_skips_second_attempt_at_same_head() -> None:
    decision = decide_autorebase(
        enabled=True,
        branch="agent/issue-11595",
        pr_number=42,
        staging_sha=_SHA,
        attempted={f"42@{_SHA}"},
    )
    assert decision.action == "skipped_already_attempted"


def test_decide_attempts_again_when_staging_advances() -> None:
    """The dedup key is (pr, staging head) — a NEW head earns a new attempt."""
    decision = decide_autorebase(
        enabled=True,
        branch="agent/issue-11595",
        pr_number=42,
        staging_sha=_OTHER_SHA,
        attempted={f"42@{_SHA}"},
    )
    assert decision.action == "attempt"


def test_is_factory_branch_covers_agent_namespace_only() -> None:
    assert is_factory_branch("agent/issue-7")
    assert is_factory_branch("agent/auto-agent-7")
    assert not is_factory_branch("rc/2026-08-21-1200")


# ---------------------------------------------------------------------------
# PRAutoRebase executor
# ---------------------------------------------------------------------------


def _pr(number: int = 42, branch: str = "agent/issue-11595") -> ConflictingPR:
    return ConflictingPR(number=number, branch=branch, labels=[])


def _make(
    tmp_path: Path,
    *,
    enabled: bool = True,
    dry_run: bool = False,
    refresh_result: Any = None,
    staging_sha: str = _SHA,
) -> tuple[PRAutoRebase, AsyncMock, AsyncMock, DedupStore]:
    config = ConfigFactory.create(repo_root=tmp_path / "repo", dry_run=dry_run)
    object.__setattr__(config, "pr_autorebase_enabled", enabled)
    prs = AsyncMock()
    refresh_fn = AsyncMock(
        return_value=refresh_result
        if refresh_result is not None
        else ArchRefreshResult(status="refreshed")
    )
    dedup = DedupStore("pr_autorebase_attempts", tmp_path / "dedup.json")
    actuator = PRAutoRebase(config=config, prs=prs, refresh_fn=refresh_fn, dedup=dedup)
    actuator._staging_head_sha = AsyncMock(return_value=staging_sha)  # type: ignore[method-assign]
    return actuator, prs, refresh_fn, dedup


async def test_refreshed_outcome_is_autorebased(tmp_path: Path) -> None:
    actuator, _prs, refresh_fn, _dedup = _make(tmp_path)
    outcome = await actuator.try_autorebase(_pr())
    assert outcome == "autorebased"
    refresh_fn.assert_awaited_once()


async def test_refresh_receives_pr_branch_and_configured_base(tmp_path: Path) -> None:
    actuator, _prs, refresh_fn, _dedup = _make(tmp_path)
    await actuator.try_autorebase(_pr(branch="agent/issue-9"))
    kwargs = refresh_fn.await_args.kwargs
    assert kwargs["branch"] == "agent/issue-9"
    assert kwargs["base"] == actuator._config.base_branch()


async def test_real_conflict_surfaces_one_comment(tmp_path: Path) -> None:
    actuator, prs, _refresh_fn, _dedup = _make(
        tmp_path,
        refresh_result=ArchRefreshResult(
            status="real-conflict",
            error="non-generated merge conflict: src/app.py",
        ),
    )
    outcome = await actuator.try_autorebase(_pr())
    assert outcome == "real_conflict"
    prs.post_comment.assert_awaited_once()
    assert "src/app.py" in prs.post_comment.await_args.args[1]


async def test_engine_failure_returns_failed_without_comment(tmp_path: Path) -> None:
    actuator, prs, _refresh_fn, _dedup = _make(
        tmp_path, refresh_result=ArchRefreshResult(status="failed", error="push failed")
    )
    outcome = await actuator.try_autorebase(_pr())
    assert outcome == "failed"
    prs.post_comment.assert_not_awaited()


async def test_attempt_is_persisted_before_engine_runs(tmp_path: Path) -> None:
    """Crash-safety: the dedup key lands on disk BEFORE the rebase attempt,
    so a crash mid-rebase cannot loop against the same staging head."""
    actuator, _prs, refresh_fn, dedup = _make(tmp_path)
    refresh_fn.side_effect = RuntimeError("worktree exploded")
    outcome = await actuator.try_autorebase(_pr())
    assert outcome == "failed"
    assert f"42@{_SHA}" in dedup.get()


async def test_dedup_persists_across_instances(tmp_path: Path) -> None:
    first, _prs, _refresh_fn, _dedup = _make(tmp_path)
    await first.try_autorebase(_pr())

    second, _prs2, refresh_fn2, _dedup2 = _make(tmp_path)
    outcome = await second.try_autorebase(_pr())
    assert outcome == "skipped_already_attempted"
    refresh_fn2.assert_not_awaited()


async def test_stale_head_keys_are_pruned_on_new_attempt(tmp_path: Path) -> None:
    """Keys for superseded staging heads can never be consulted again (the
    decision keys on the CURRENT head), so recording prunes them — the dedup
    file stays bounded at one head's worth of PRs."""
    actuator, _prs, _refresh_fn, dedup = _make(tmp_path, staging_sha=_OTHER_SHA)
    dedup.add(f"7@{_SHA}")
    await actuator.try_autorebase(_pr())
    assert dedup.get() == {f"42@{_OTHER_SHA}"}


async def test_disabled_flag_short_circuits(tmp_path: Path) -> None:
    actuator, _prs, refresh_fn, _dedup = _make(tmp_path, enabled=False)
    outcome = await actuator.try_autorebase(_pr())
    assert outcome == "skipped_disabled"
    refresh_fn.assert_not_awaited()


async def test_non_factory_branch_short_circuits(tmp_path: Path) -> None:
    actuator, _prs, refresh_fn, _dedup = _make(tmp_path)
    outcome = await actuator.try_autorebase(_pr(branch="feat/human-work"))
    assert outcome == "skipped_not_factory"
    refresh_fn.assert_not_awaited()


async def test_unknown_staging_sha_skips_without_attempt(tmp_path: Path) -> None:
    actuator, _prs, refresh_fn, dedup = _make(tmp_path, staging_sha="")
    outcome = await actuator.try_autorebase(_pr())
    assert outcome == "skipped_no_staging_sha"
    refresh_fn.assert_not_awaited()
    assert dedup.get() == set()


async def test_dry_run_neither_rebases_nor_burns_the_attempt(tmp_path: Path) -> None:
    actuator, _prs, refresh_fn, dedup = _make(tmp_path, dry_run=True)
    outcome = await actuator.try_autorebase(_pr())
    assert outcome == "skipped_dry_run"
    refresh_fn.assert_not_awaited()
    assert dedup.get() == set()


async def test_credit_exhaustion_propagates(tmp_path: Path) -> None:
    """Dark-factory contract: CreditExhaustedError must escape the broad
    except so the loop pauses instead of burning attempts."""
    from subprocess_util import CreditExhaustedError

    actuator, _prs, refresh_fn, _dedup = _make(tmp_path)
    refresh_fn.side_effect = CreditExhaustedError("credit out")
    with pytest.raises(CreditExhaustedError):
        await actuator.try_autorebase(_pr())


async def test_likely_bug_propagates(tmp_path: Path) -> None:
    actuator, _prs, refresh_fn, _dedup = _make(tmp_path)
    refresh_fn.side_effect = TypeError("wrong signature")
    with pytest.raises(TypeError):
        await actuator.try_autorebase(_pr())


# ---------------------------------------------------------------------------
# Config / registry wiring
# ---------------------------------------------------------------------------


def test_kill_switch_defaults_off() -> None:
    """A force-pushing-adjacent actuator must ship default OFF (#11595):
    the operator arms HYDRAFLOW_PR_AUTOREBASE_ENABLED deliberately."""
    from config import HydraFlowConfig

    assert HydraFlowConfig(repo="acme/widgets").pr_autorebase_enabled is False


def test_env_override_is_registered() -> None:
    from config import _ENV_BOOL_OVERRIDES

    assert (
        "pr_autorebase_enabled",
        "HYDRAFLOW_PR_AUTOREBASE_ENABLED",
        False,
    ) in _ENV_BOOL_OVERRIDES


def test_settings_registry_exposes_the_kill_switch() -> None:
    from settings_registry import SETTINGS

    assert "pr_autorebase_enabled" in SETTINGS
