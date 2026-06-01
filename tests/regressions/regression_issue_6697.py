"""Regression test for issue #6697.

Bug: ``workspace.py`` lazily populates ``_FETCH_LOCKS`` and ``_WORKTREE_LOCKS``
via a check-then-set pattern (``get`` -> ``if None`` -> create -> store) with no
synchronization.  Under concurrent access, two callers can each create a
separate ``asyncio.Lock`` for the same key, defeating the mutual exclusion that
protects git fetch and worktree create/destroy operations.

These tests use ``threading`` to force two callers into the vulnerable window
between ``dict.get`` returning ``None`` and the new lock being stored.  A custom
dict subclass injects a ``threading.Barrier`` at exactly that point so both
threads observe ``None`` before either writes — deterministic TOCTOU.

The tests will FAIL (RED) against the current code and pass once the lock-dict
mutations are made atomic (e.g. via ``dict.setdefault``).
"""

from __future__ import annotations

import pytest

import asyncio
import threading
from pathlib import Path
from unittest.mock import patch

import workspace
from tests.helpers import ConfigFactory


class _RacyDict(dict):
    """Dict subclass that forces a context switch after ``get()`` returns None.

    When ``get`` returns ``None`` (key not yet populated), both threads will
    wait at the barrier before either can store a new lock — this deterministically
    triggers the TOCTOU window.
    """

    def __init__(self, barrier: threading.Barrier, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._barrier = barrier

    def get(self, key, default=None):
        result = super().get(key, default)
        if result is None:
            # Force both threads to reach this point before either continues
            # to the ``if lock is None: lock = asyncio.Lock()`` assignment.
            self._barrier.wait(timeout=5)
        return result


class TestIssue6697FetchLockRace:
    """_repo_fetch_lock() TOCTOU: two threads must get the same Lock object."""

    @pytest.mark.xfail(reason="Regression for issue #6697 — fix not yet landed", strict=False)
    def test_concurrent_callers_get_same_fetch_lock(self, tmp_path: Path) -> None:
        """Two threads calling _repo_fetch_lock() for the same repo key must
        receive the identical asyncio.Lock instance.

        Currently FAILS because both threads see ``None`` from the dict get,
        each create their own ``asyncio.Lock()``, and only one survives in the
        dict — the other caller holds a private lock that provides no mutual
        exclusion.
        """
        barrier = threading.Barrier(2, timeout=5)
        racy_dict: _RacyDict = _RacyDict(barrier)

        config = ConfigFactory.create(repo_root=tmp_path)
        results: list[asyncio.Lock | None] = [None, None]
        errors: list[Exception | None] = [None, None]

        def worker(index: int) -> None:
            try:
                mgr = workspace.WorkspaceManager(config)
                results[index] = mgr._repo_fetch_lock()
            except Exception as exc:
                errors[index] = exc

        with patch.object(workspace, "_FETCH_LOCKS", racy_dict):
            t1 = threading.Thread(target=worker, args=(0,))
            t2 = threading.Thread(target=worker, args=(1,))
            t1.start()
            t2.start()
            t1.join(timeout=10)
            t2.join(timeout=10)

        # Propagate any worker errors so they surface clearly.
        for i, err in enumerate(errors):
            if err is not None:
                raise AssertionError(f"worker {i} raised: {err}") from err

        assert results[0] is not None, "worker 0 did not return a lock"
        assert results[1] is not None, "worker 1 did not return a lock"

        # BUG: each thread created its own Lock — they are different objects.
        assert results[0] is results[1], (
            f"Two callers got different Lock objects for the same repo key — "
            f"TOCTOU race in _repo_fetch_lock() (issue #6697). "
            f"Lock 0: {id(results[0]):#x}, Lock 1: {id(results[1]):#x}"
        )


class TestIssue6697WorkspaceLockRace:
    """_repo_workspace_lock() TOCTOU: two threads must get the same Lock object."""

    @pytest.mark.xfail(reason="Regression for issue #6697 — fix not yet landed", strict=False)
    def test_concurrent_callers_get_same_workspace_lock(self, tmp_path: Path) -> None:
        """Two threads calling _repo_workspace_lock() for the same repo slug
        must receive the identical asyncio.Lock instance.

        Currently FAILS for the same reason as the fetch lock test — the
        check-then-set on ``_WORKTREE_LOCKS`` has no guard.
        """
        barrier = threading.Barrier(2, timeout=5)
        racy_dict: _RacyDict = _RacyDict(barrier)

        config = ConfigFactory.create(repo_root=tmp_path)
        results: list[asyncio.Lock | None] = [None, None]
        errors: list[Exception | None] = [None, None]

        def worker(index: int) -> None:
            try:
                mgr = workspace.WorkspaceManager(config)
                results[index] = mgr._repo_workspace_lock()
            except Exception as exc:
                errors[index] = exc

        with patch.object(workspace, "_WORKTREE_LOCKS", racy_dict):
            t1 = threading.Thread(target=worker, args=(0,))
            t2 = threading.Thread(target=worker, args=(1,))
            t1.start()
            t2.start()
            t1.join(timeout=10)
            t2.join(timeout=10)

        for i, err in enumerate(errors):
            if err is not None:
                raise AssertionError(f"worker {i} raised: {err}") from err

        assert results[0] is not None, "worker 0 did not return a lock"
        assert results[1] is not None, "worker 1 did not return a lock"

        assert results[0] is results[1], (
            f"Two callers got different Lock objects for the same repo slug — "
            f"TOCTOU race in _repo_workspace_lock() (issue #6697). "
            f"Lock 0: {id(results[0]):#x}, Lock 1: {id(results[1]):#x}"
        )
