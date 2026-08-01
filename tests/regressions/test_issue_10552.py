"""Regression for #10552 — RC promotion must update-branch via MERGE, not rebase.

Root cause: ``PRManager.merge_promotion_pr(auto_rebase=True)`` recovers from a
failed ``gh pr merge --merge`` (the RC head is always behind ``main`` by the
main-only synthetic ``chore(rc)`` + merge commits) by calling
``_rebase_and_recheck_ci``, which called ``update_pr_branch`` with the default
``method="rebase"``. GitHub ``update_method=rebase`` rewrites every RC commit
SHA (new parent, committer flips to the factory identity), so ``main`` and
``staging`` become non-ancestors → the next RC merge conflicts → recovery
rebases again → self-perpetuating SHA divergence.

Fix: the promotion recovery path updates the branch with ``method="merge"``
(GitHub's own default for update-branch), which preserves the RC commit SHAs.
The regular ``merge_pr`` path uses ``--squash`` (which discards pre-merge SHAs
anyway), so its recovery must keep the default ``method="rebase"``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from tests.helpers import ConfigFactory, make_pr_manager


def _make_pr_manager() -> Any:
    config = ConfigFactory.create(repo="owner/repo")
    return make_pr_manager(config=config, event_bus=AsyncMock())


@pytest.mark.asyncio
async def test_promotion_recovery_updates_branch_via_merge_not_rebase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First ``--merge`` fails → update-branch API is called with
    ``update_method=merge`` (SHA-preserving), then merge retries and succeeds."""
    pm = _make_pr_manager()
    merge_calls = 0

    async def _flaky_subprocess(*cmd: str, **_kw: Any) -> str:
        nonlocal merge_calls
        if "merge" in cmd:
            merge_calls += 1
            if merge_calls == 1:
                raise RuntimeError("Pull Request is not mergeable: behind base")
            return ""
        return ""

    gh_calls: list[tuple[str, ...]] = []

    async def _capture_gh(*cmd: str, cwd: Any = None) -> str:
        gh_calls.append(cmd)
        return ""

    async def _ci_passes(*_a: Any, **_kw: Any) -> tuple[bool, str]:
        return True, "CI passed"

    monkeypatch.setattr("pr_manager_promotion.run_subprocess", _flaky_subprocess)
    monkeypatch.setattr(pm, "_run_gh", _capture_gh)
    monkeypatch.setattr(pm, "wait_for_ci", _ci_passes)

    ok = await pm.merge_promotion_pr(99, auto_rebase=True)

    assert ok is True
    assert merge_calls == 2  # first failed, second (post-update) succeeded

    update_branch_calls = [
        c for c in gh_calls if any("update-branch" in str(x) for x in c)
    ]
    assert update_branch_calls, "update-branch API was never called during recovery"
    flat = update_branch_calls[0]
    assert any("update_method=merge" in str(x) for x in flat), (
        f"promotion recovery must update-branch via merge (SHA-preserving); "
        f"got {flat!r}"
    )
    assert not any("update_method=rebase" in str(x) for x in flat), (
        "promotion recovery must NOT rebase — that rewrites RC SHAs and diverges "
        "main from staging"
    )


@pytest.mark.asyncio
async def test_regular_merge_recovery_still_uses_rebase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The squash-based ``merge_pr`` recovery must keep ``update_method=rebase``.

    Squash discards pre-merge SHAs regardless, so rebase-update is fine and must
    not regress to merge (which would leave stale merge commits on the head)."""
    pm = _make_pr_manager()
    merge_calls = 0

    async def _flaky_subprocess(*cmd: str, **_kw: Any) -> str:
        nonlocal merge_calls
        if "merge" in cmd:
            merge_calls += 1
            if merge_calls == 1:
                raise RuntimeError("Pull Request is not mergeable: behind base")
            return ""
        return ""

    gh_calls: list[tuple[str, ...]] = []

    async def _capture_gh(*cmd: str, cwd: Any = None) -> str:
        gh_calls.append(cmd)
        return ""

    async def _ci_passes(*_a: Any, **_kw: Any) -> tuple[bool, str]:
        return True, "CI passed"

    monkeypatch.setattr("pr_manager.run_subprocess", _flaky_subprocess)
    monkeypatch.setattr(pm, "_run_gh", _capture_gh)
    monkeypatch.setattr(pm, "wait_for_ci", _ci_passes)
    monkeypatch.setattr(pm, "get_pr_title_and_body", AsyncMock(return_value=("t", "b")))

    ok = await pm.merge_pr(42, auto_rebase=True)

    assert ok is True
    assert merge_calls == 2

    update_branch_calls = [
        c for c in gh_calls if any("update-branch" in str(x) for x in c)
    ]
    assert update_branch_calls, "update-branch API was never called during recovery"
    flat = update_branch_calls[0]
    assert any("update_method=rebase" in str(x) for x in flat), (
        f"regular squash-merge recovery must keep rebase-update; got {flat!r}"
    )
