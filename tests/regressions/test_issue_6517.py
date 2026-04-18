"""Regression test for issue #6517.

Bug: BeadsNotInstalledError at line 86 of beads_manager.py is raised inside
``except FileNotFoundError as exc`` but missing ``from exc``, unlike the
identical patterns at lines 96 and 108. This means the original
FileNotFoundError traceback is lost when npm is missing.

Expected behaviour after fix:
  - ``BeadsNotInstalledError.__cause__`` is the original ``FileNotFoundError``
    (i.e. ``from exc`` is present).

These tests assert the *correct* behaviour (exception chaining via ``from exc``),
so they are RED against buggy code that lacks ``from exc``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from beads_manager import BeadsManager, BeadsNotInstalledError  # noqa: E402


class TestBeadsNotInstalledErrorChaining:
    """Issue #6517 — BeadsNotInstalledError must chain to the original
    FileNotFoundError via ``from exc`` so debuggers can see the root cause.
    """

    @pytest.mark.asyncio
    async def test_npm_not_found_chains_original_file_not_found_error(self) -> None:
        """When ``bd --version`` fails and ``npm install`` raises
        FileNotFoundError (npm not installed), the resulting
        BeadsNotInstalledError must have ``__cause__`` set to the original
        FileNotFoundError.

        Bug: ``raise BeadsNotInstalledError(...)`` without ``from exc``
        loses the original exception context.
        """
        original_fnf = FileNotFoundError("npm: command not found")

        # bd --version fails (bd not installed)
        mock_bd_version = AsyncMock(side_effect=FileNotFoundError("bd not found"))
        # npm install fails (npm not installed)
        mock_npm_install = AsyncMock(side_effect=original_fnf)

        async def fake_run_subprocess(*cmd, **kwargs):
            if cmd[0] == "bd":
                return await mock_bd_version(*cmd, **kwargs)
            if cmd[0] == "npm":
                return await mock_npm_install(*cmd, **kwargs)
            raise AssertionError(f"Unexpected command: {cmd}")

        manager = BeadsManager()

        with patch("beads_manager.run_subprocess", side_effect=fake_run_subprocess):
            with pytest.raises(BeadsNotInstalledError) as exc_info:
                await manager.ensure_installed()

        # The key assertion: __cause__ must be the original FileNotFoundError.
        # Without ``from exc``, __cause__ is None and the traceback is lost.
        assert exc_info.value.__cause__ is not None, (
            "BeadsNotInstalledError.__cause__ is None — "
            "the 'from exc' chain is missing at line 86"
        )
        assert isinstance(exc_info.value.__cause__, FileNotFoundError), (
            f"Expected __cause__ to be FileNotFoundError, "
            f"got {type(exc_info.value.__cause__)}"
        )

    @pytest.mark.asyncio
    async def test_npm_not_found_cause_is_exact_original_exception(self) -> None:
        """The chained cause must be the *exact* FileNotFoundError instance
        that was caught, not a new one.
        """
        original_fnf = FileNotFoundError("npm: command not found")

        async def fake_run_subprocess(*cmd, **kwargs):
            if cmd[0] == "bd":
                raise FileNotFoundError("bd not found")
            if cmd[0] == "npm":
                raise original_fnf
            raise AssertionError(f"Unexpected command: {cmd}")

        manager = BeadsManager()

        with patch("beads_manager.run_subprocess", side_effect=fake_run_subprocess):
            with pytest.raises(BeadsNotInstalledError) as exc_info:
                await manager.ensure_installed()

        assert exc_info.value.__cause__ is original_fnf, (
            "BeadsNotInstalledError.__cause__ is not the original "
            "FileNotFoundError instance — exception chaining is broken"
        )
