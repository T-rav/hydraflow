"""Regression test for issue #6381.

Bug: ``probe_credit_availability()`` in ``subprocess_util.py`` catches all
exceptions (``except Exception``) and returns ``False`` (credits unavailable).
This means any transient network error (DNS failure, connection timeout, proxy
issue) causes the probe to report "no credits" — which halts agent scheduling
unnecessarily.

Expected behaviour after fix:
  - Transient network errors (``httpx.ConnectError``, ``httpx.TimeoutException``,
    ``OSError``) return ``True`` (assume credits available, don't block agents).
  - Only genuine credit-exhaustion responses cause ``False``.
  - The broad ``except Exception`` is narrowed to expected HTTP/network errors.

These tests assert the CORRECT (post-fix) behaviour and are therefore RED
against the current buggy code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from subprocess_util import probe_credit_availability  # noqa: E402


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the probe doesn't short-circuit due to missing API key."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")


class TestProbeReturnsAvailableOnTransientNetworkErrors:
    """probe_credit_availability must return True on transient network errors.

    The current code returns False (credits unavailable) for ANY exception,
    including transient network problems.  This is the bug: a DNS failure or
    connection timeout should not be treated as credit exhaustion.
    """

    @pytest.mark.asyncio
    async def test_connect_error_returns_true(self) -> None:
        """A ConnectError (DNS failure, connection refused) is transient.

        After fix, the probe should return True (assume credits available).
        """
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("DNS resolution failed"),
        )

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await probe_credit_availability()

        assert result is True, (
            "ConnectError (transient network) should return True (credits assumed available), "
            "but got False — agents will stall unnecessarily"
        )

    @pytest.mark.asyncio
    async def test_timeout_exception_returns_true(self) -> None:
        """A TimeoutException means the network is slow, not that credits are gone.

        After fix, the probe should return True.
        """
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=httpx.TimeoutException("Connection timed out"),
        )

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await probe_credit_availability()

        assert result is True, (
            "TimeoutException (transient network) should return True, "
            "but got False — agents will stall unnecessarily"
        )

    @pytest.mark.asyncio
    async def test_os_error_returns_true(self) -> None:
        """An OSError (e.g. network unreachable) is transient.

        After fix, the probe should return True.
        """
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=OSError("Network is unreachable"),
        )

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await probe_credit_availability()

        assert result is True, (
            "OSError (transient network) should return True, "
            "but got False — agents will stall unnecessarily"
        )


class TestProbeDoesNotMaskUnexpectedErrors:
    """The broad ``except Exception`` masks bugs like KeyError or TypeError.

    After fix, unexpected errors should propagate instead of silently
    returning False.
    """

    @pytest.mark.asyncio
    async def test_key_error_is_not_swallowed(self) -> None:
        """A KeyError in response parsing is a real bug, not a network error.

        After fix, it should propagate (not be caught and turned into False).
        """
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=KeyError("unexpected_field"),
        )

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(KeyError):
                await probe_credit_availability()
