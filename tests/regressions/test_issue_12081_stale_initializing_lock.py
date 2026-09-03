"""A worktree whose creation died must not be immortal.

`git worktree add` writes `.git/worktrees/<name>/locked` with the reason
`initializing` and clears it on success. Killed partway, the lock stands
forever — and every phase of the GC then declines it for a different, locally
correct reason: `parse_git_worktrees` drops locked rows, and
`dead_registrations` deliberately leaves a lock alone while the directory
exists ("the lock is not ours to break").

Two such worktrees were found on 2026-09-02, both created the previous day,
holding 3.2 GB between them and unreapable by any phase (#12081). They came
back only to a manual `git worktree unlock` followed by `remove --force`.

What makes them safely distinguishable is the lock's REASON plus its age: a
lock a person took says why, `initializing` is git's own, and one older than a
whole checkout could take describes an operation that is not coming back.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from workspace_gc_landed_safety import stale_initializing_worktrees

_GRACE = 3600.0
_NOW = 1_800_000_000.0


def _register(
    git_dir: Path, name: str, *, reason: str | None, age_s: float, exists: bool = True
) -> Path:
    """Create one registered worktree, optionally locked, and return its path."""
    admin = git_dir / "worktrees" / name
    admin.mkdir(parents=True)
    checkout = git_dir.parent / "trees" / name
    if exists:
        checkout.mkdir(parents=True)
    (admin / "gitdir").write_text(f"{checkout / '.git'}\n", encoding="utf-8")
    if reason is not None:
        lock = admin / "locked"
        lock.write_text(reason, encoding="utf-8")
        mtime = _NOW - age_s
        os.utime(lock, (mtime, mtime))
    return checkout


@pytest.fixture
def git_dir(tmp_path: Path) -> Path:
    d = tmp_path / "repo" / ".git"
    d.mkdir(parents=True)
    return d


def test_an_abandoned_initializing_lock_is_reported(git_dir: Path) -> None:
    path = _register(git_dir, "dead", reason="initializing", age_s=_GRACE * 24)

    assert stale_initializing_worktrees("", git_dir=git_dir, now=_NOW) == [path]


def test_a_creation_still_in_progress_is_left_alone(git_dir: Path) -> None:
    """The decoy that matters: a worktree being created RIGHT NOW looks the
    same minus the elapsed time, and reaping it would delete a tree out from
    under the process making it."""
    _register(git_dir, "inflight", reason="initializing", age_s=5.0)

    assert stale_initializing_worktrees("", git_dir=git_dir, now=_NOW) == []


@pytest.mark.parametrize("reason", ["operator hold", "bisect in progress", ""])
def test_any_other_lock_reason_is_never_reaped(git_dir: Path, reason: str) -> None:
    """Age does not license breaking a lock someone took deliberately."""
    _register(git_dir, "held", reason=reason, age_s=_GRACE * 100)

    assert stale_initializing_worktrees("", git_dir=git_dir, now=_NOW) == []


def test_an_unlocked_worktree_is_not_this_function_s_business(git_dir: Path) -> None:
    _register(git_dir, "normal", reason=None, age_s=0)

    assert stale_initializing_worktrees("", git_dir=git_dir, now=_NOW) == []


def test_a_vanished_checkout_is_left_to_dead_registrations(git_dir: Path) -> None:
    """Directory gone is #11908's case, and it is already handled there —
    reporting it here too would have two phases racing to remove one path."""
    _register(
        git_dir, "phantom", reason="initializing", age_s=_GRACE * 24, exists=False
    )

    assert stale_initializing_worktrees("", git_dir=git_dir, now=_NOW) == []


def test_the_age_comes_from_the_lock_not_the_directory(git_dir: Path) -> None:
    """A half-created tree carries a FRESH directory mtime from the checkout
    that died, so dating it by the directory would keep every abandoned lock
    permanently young — which is the bug, not a variation on it."""
    path = _register(git_dir, "dead", reason="initializing", age_s=_GRACE * 24)
    # The lock is a day old; the directory was touched a moment ago.
    now = time.time()
    os.utime(path, (now, now))

    assert stale_initializing_worktrees("", git_dir=git_dir, now=_NOW) == [path], (
        "a fresh directory mtime hid an abandoned lock — the window must be "
        "measured on the lock file"
    )


# ---------------------------------------------------------------------------
# The reap's except clause is narrower than its sibling phases' blind catches
# (the suppressions ratchet only shrinks). Narrowing must not quietly change
# which signals escape.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credit_exhaustion_escapes_the_reap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CreditExhaustedError subclasses RuntimeError, so the narrowed clause
    catches it — `reraise_on_credit_or_bug` is what puts it back.

    Without that call the loop logs "could not reap" and burns its attempt
    budget against an exhausted account (CLAUDE.md, dark-factory §2.2).
    """
    import workspace_gc_loop
    from subprocess_util import CreditExhaustedError

    monkeypatch.setattr(
        workspace_gc_loop,
        "stale_initializing_worktrees",
        lambda *_a, **_k: [tmp_path / "abandoned"],
    )

    async def _boom(*_a: object, **_k: object) -> None:
        raise CreditExhaustedError("weekly limit")

    monkeypatch.setattr(workspace_gc_loop, "run_subprocess", _boom)

    with pytest.raises(CreditExhaustedError):
        await workspace_gc_loop._reap_abandoned_creations(
            repo_root=tmp_path, gh_token="t", now=0.0
        )


@pytest.mark.asyncio
async def test_a_git_failure_is_logged_and_the_sweep_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One unreapable tree must not abort the others — the decoy for the
    reraise above, which would otherwise be satisfied by removing the catch."""
    import workspace_gc_loop

    first, second = tmp_path / "a", tmp_path / "b"
    monkeypatch.setattr(
        workspace_gc_loop,
        "stale_initializing_worktrees",
        lambda *_a, **_k: [first, second],
    )

    seen: list[str] = []

    async def _git(*argv: str, **_k: object) -> None:
        seen.append(argv[-1])
        if str(first) in argv:
            raise RuntimeError("worktree is dirty")

    monkeypatch.setattr(workspace_gc_loop, "run_subprocess", _git)

    reaped = await workspace_gc_loop._reap_abandoned_creations(
        repo_root=tmp_path, gh_token="t", now=0.0
    )

    assert reaped == 1
    assert str(second) in seen
