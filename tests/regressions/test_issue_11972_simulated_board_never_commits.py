"""#11972 — a simulated board's issue numbers reached tracked files.

Twenty fake pins (#25–#44) were written into `docs/wiki/memory-feedback/` by a
sandbox/scenario run of `MemoryBacklogLoop` whose FakeGitHub numbers issues
from a counter, and were merged in PR #8989. #12002 repaired the damage; this
stops it recurring.

The containment is at the COMMIT, not the write. Updating frontmatter in a
tmp-path repo is harmless and the scenario layer depends on it; committing into
a live checkout is what made fake numbers durable and mergeable.

An earlier attempt guarded on the NUMBER — refusing any pin below a
plausibility floor. That was wrong and is recorded here so it is not retried:
it cannot tell a harmless write into a tmp repo from a harmful one into a real
checkout, so it would have broken legitimate scenario tests while catching the
real problem only by coincidence. The distinguishing fact is not the number, it
is whether the board is real.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestTheFakeDeclaresItself:
    def test_fake_github_is_marked_simulated(self) -> None:
        from mockworld.fakes.fake_github import FakeGitHub

        assert FakeGitHub.is_simulated is True

    def test_the_real_adapter_is_not(self) -> None:
        """Absence is the signal — the real adapter says nothing."""
        from pr_manager import PRManager

        assert getattr(PRManager, "is_simulated", False) is not True

    def test_a_bare_mock_is_not_treated_as_simulated(self) -> None:
        """The check must be `is True`, not truthiness.

        An AsyncMock answers every attribute with a truthy Mock, so a loose
        check would call every mock-based test a simulation and silently stop
        committing in all of them.
        """
        assert getattr(AsyncMock(), "is_simulated", False) is not True


class TestTheCommitIsRefused:
    @staticmethod
    def _loop(simulated: bool):
        from memory_backlog_loop import MemoryBacklogLoop

        loop = MagicMock(spec=MemoryBacklogLoop)
        loop._pr = MagicMock()
        if simulated:
            loop._pr.is_simulated = True
        else:
            del loop._pr.is_simulated
        loop._config = MagicMock()
        loop._config.repo_root = "/repo"
        return loop

    @pytest.mark.asyncio
    async def test_a_simulated_board_does_not_reach_git(self, monkeypatch) -> None:
        import memory_backlog_loop

        from memory_backlog_loop import MemoryBacklogLoop

        ran = AsyncMock()
        monkeypatch.setattr(memory_backlog_loop, "run_subprocess_result", ran)

        await MemoryBacklogLoop._commit_mirror_updates(self._loop(True), [11947])

        ran.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_ordinary_mock_port_still_commits(self, monkeypatch) -> None:
        """The mutation that a direct AsyncMock assertion cannot catch.

        Most tests in this repo pass a bare mock as the PR port, and a mock
        answers `is_simulated` with a truthy Mock. A loose `if getattr(...)`
        would therefore treat EVERY mock-based test as a simulation and stop
        committing in all of them — green, and silently wrong. Only driving the
        loop with an undoctored mock shows the difference.
        """
        import memory_backlog_loop

        from memory_backlog_loop import MemoryBacklogLoop

        ran = AsyncMock(return_value=MagicMock(returncode=0, stderr=""))
        monkeypatch.setattr(memory_backlog_loop, "run_subprocess_result", ran)
        loop = MagicMock(spec=MemoryBacklogLoop)
        loop._pr = AsyncMock()  # answers `is_simulated` with a truthy Mock
        loop._config = MagicMock()
        loop._config.repo_root = "/repo"

        await MemoryBacklogLoop._commit_mirror_updates(loop, [11947])

        ran.assert_awaited()

    @pytest.mark.asyncio
    async def test_a_real_board_still_commits(self, monkeypatch) -> None:
        # The decoy. A loop that never committed would satisfy the test above
        # while dropping the audit trail ADR-0089 requires.
        import memory_backlog_loop

        from memory_backlog_loop import MemoryBacklogLoop

        ran = AsyncMock(return_value=MagicMock(returncode=0, stderr=""))
        monkeypatch.setattr(memory_backlog_loop, "run_subprocess_result", ran)

        await MemoryBacklogLoop._commit_mirror_updates(self._loop(False), [11947])

        ran.assert_awaited()
