"""Superseding regression contract for issue #6517.

Factory Beads no longer discovers or installs a CLI. The direct JSONL manager's
``ensure_installed`` compatibility hook must therefore succeed without spawning
anything, eliminating the historical missing-npm exception path entirely.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from beads_manager import BeadsManager, BeadsNotInstalledError  # noqa: E402


class TestBeadsNoInstallDependency:
    @pytest.mark.asyncio()
    async def test_ensure_installed_never_spawns_a_process(self) -> None:
        with patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(side_effect=AssertionError("subprocess must not run")),
        ) as spawn:
            await BeadsManager().ensure_installed()

        spawn.assert_not_awaited()

    def test_legacy_exception_symbol_remains_importable(self) -> None:
        assert issubclass(BeadsNotInstalledError, RuntimeError)
