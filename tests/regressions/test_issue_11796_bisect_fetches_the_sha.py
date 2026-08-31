"""Regression: the bisect loop fetches an RC sha before checking it out.

`_create_worktree` ran `git worktree add --detach <dir> <rc_sha>` with no
fetch, and the loop's only `git fetch` lives in the auto-revert path much
later. RC branches are DELETED after promotion, so an RC sha the loop wants to
bisect is routinely absent locally.

Git reports that as `fatal: invalid reference`, which reads like a corrupt
argument rather than a missing object — so the loop raised
`bisect-harness-failure` and escalated to HITL for a sha the repo had simply
never fetched. Measured 2026-08-30 (#11796):

    git worktree add failed for a25456b8f7ee…: rc=128
    stderr=fatal: invalid reference: a25456b8f7ee…

The sha was genuinely not in the local object store (`git cat-file -e` failed),
while its range partner `6d31fefbcf87` resolved fine — the tell that this was a
fetch gap, not corruption.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from staging_bisect_loop import StagingBisectLoop

SHA = "a25456b8f7ee08125f4845b6c0800ae396867bd5"


def _loop(git: AsyncMock) -> StagingBisectLoop:
    loop = StagingBisectLoop.__new__(StagingBisectLoop)
    loop._config = MagicMock()
    loop._run_git = git
    return loop


def _git(*results: tuple[int, str, str]) -> AsyncMock:
    return AsyncMock(side_effect=list(results))


def _commands(git: AsyncMock) -> list[list[str]]:
    return [call.args[0] for call in git.await_args_list]


@pytest.mark.asyncio
async def test_a_present_sha_is_not_fetched() -> None:
    """The common case must stay free. A fetch on every bisect step would add
    a network round trip to a loop that already runs per candidate commit."""
    git = _git((0, "", ""))  # cat-file succeeds

    await _loop(git)._ensure_sha_present(SHA)

    assert len(_commands(git)) == 1
    assert _commands(git)[0][:2] == ["git", "cat-file"]


@pytest.mark.asyncio
async def test_a_missing_sha_is_fetched_directly() -> None:
    git = _git((1, "", "missing"), (0, "", ""))  # cat-file fails, fetch works

    await _loop(git)._ensure_sha_present(SHA)

    commands = _commands(git)
    assert commands[1] == ["git", "fetch", "origin", SHA], (
        "the sha must be fetched by object, not left to a blind full fetch"
    )


@pytest.mark.asyncio
async def test_a_direct_fetch_failure_falls_back_to_a_full_fetch() -> None:
    """Servers without reachable-sha1-in-want reject a by-object fetch; the
    sha may still be reachable from a ref this clone has not seen."""
    git = _git((1, "", "missing"), (128, "", "not our ref"), (0, "", ""))

    await _loop(git)._ensure_sha_present(SHA)

    assert _commands(git)[2] == ["git", "fetch", "origin"]


@pytest.mark.asyncio
async def test_an_unreachable_sha_still_reaches_the_caller() -> None:
    """Best-effort, deliberately. A sha force-pushed away or GC'd upstream is a
    REAL harness failure and must still surface as one — this fix removes the
    avoidable half, not the diagnosis.
    """
    git = _git((1, "", "missing"), (128, "", "no"), (128, "", "no"))

    await _loop(git)._ensure_sha_present(SHA)  # must not raise

    # Nothing swallowed: the caller's `worktree add` is what reports it.
    assert len(_commands(git)) == 3
