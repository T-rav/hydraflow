"""Regression test for issue #6709.

Bug: ``IssueFetcher.fetch_all_hydraflow_issues`` wraps
``_fetch_all_graphql()`` in a broad ``except Exception as exc`` and falls
back to the REST API.  If the GraphQL call fails due to
``AuthenticationError`` or ``CreditExhaustedError``, the exception is
caught, logged as a generic warning, and the REST fallback is attempted —
which will also fail.  This causes two GitHub API calls to fail instead
of one, and the fatal error is swallowed on the first call rather than
propagating immediately for the orchestrator's auth-retry logic.

These tests FAIL (RED) against the current code because
``fetch_all_hydraflow_issues`` catches the fatal exceptions and attempts
the REST fallback instead of re-raising them.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from config import Credentials, HydraFlowConfig
from issue_fetcher import IssueFetcher
from subprocess_util import AuthenticationError, CreditExhaustedError


class TestIssue6709AuthErrorNotSwallowed:
    """AuthenticationError and CreditExhaustedError must propagate from
    fetch_all_hydraflow_issues without attempting the REST fallback."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6709 — fix not yet landed", strict=False)
    async def test_authentication_error_propagates_immediately(
        self, config: HydraFlowConfig
    ) -> None:
        """fetch_all_hydraflow_issues must re-raise AuthenticationError
        from _fetch_all_graphql without falling back to REST.

        Currently FAILS because the broad ``except Exception`` catches
        AuthenticationError and calls the REST fallback path.
        """
        fetcher = IssueFetcher(config, Credentials(gh_token="expired-token"))

        with (
            patch.object(
                fetcher,
                "_fetch_all_graphql",
                new_callable=AsyncMock,
                side_effect=AuthenticationError("Bad credentials"),
            ),
            patch.object(
                fetcher,
                "fetch_issues_by_labels",
                new_callable=AsyncMock,
            ) as mock_rest,
        ):
            with pytest.raises(AuthenticationError, match="Bad credentials"):
                await fetcher.fetch_all_hydraflow_issues()

            # The REST fallback must NOT have been called.
            mock_rest.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6709 — fix not yet landed", strict=False)
    async def test_credit_exhausted_error_propagates_immediately(
        self, config: HydraFlowConfig
    ) -> None:
        """fetch_all_hydraflow_issues must re-raise CreditExhaustedError
        from _fetch_all_graphql without falling back to REST.

        Currently FAILS because the broad ``except Exception`` catches
        CreditExhaustedError and calls the REST fallback path.
        """
        fetcher = IssueFetcher(config, Credentials(gh_token="test-token"))

        with (
            patch.object(
                fetcher,
                "_fetch_all_graphql",
                new_callable=AsyncMock,
                side_effect=CreditExhaustedError("API credits exhausted"),
            ),
            patch.object(
                fetcher,
                "fetch_issues_by_labels",
                new_callable=AsyncMock,
            ) as mock_rest,
        ):
            with pytest.raises(CreditExhaustedError, match="API credits exhausted"):
                await fetcher.fetch_all_hydraflow_issues()

            # The REST fallback must NOT have been called.
            mock_rest.assert_not_called()

    @pytest.mark.asyncio
    async def test_generic_exception_still_falls_back_to_rest(
        self, config: HydraFlowConfig
    ) -> None:
        """Other exceptions should still trigger the REST fallback —
        this is a sanity check that the fix doesn't break the existing
        fallback behavior for non-fatal errors.

        This test should PASS on both the current (buggy) and fixed code.
        """
        fetcher = IssueFetcher(config, Credentials(gh_token="test-token"))

        with (
            patch.object(
                fetcher,
                "_fetch_all_graphql",
                new_callable=AsyncMock,
                side_effect=RuntimeError("GraphQL transient error"),
            ),
            patch.object(
                fetcher,
                "fetch_issues_by_labels",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_rest,
        ):
            result = await fetcher.fetch_all_hydraflow_issues()

            assert result == []
            mock_rest.assert_called_once()
