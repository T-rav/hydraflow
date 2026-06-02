"""Regression test for issue #6653.

Bug: ``_fetch_all_graphql`` (line 368) performs
``owner, name = self._config.repo.split("/", 1)`` without any slash guard.
When ``config.repo`` is misconfigured (empty string or missing slash), this
raises ``ValueError: not enough values to unpack`` instead of a descriptive
error message.

The ``__init__`` method (line 31) already has a guard
(``if "/" in config.repo``), but ``_fetch_all_graphql`` does not.

These tests FAIL (RED) against the current code because the unguarded split
raises a raw ``ValueError`` with an opaque message rather than a descriptive
one indicating the ``config.repo`` format requirement.
"""

from __future__ import annotations

import pytest

from config import Credentials, HydraFlowConfig
from issue_fetcher import IssueFetcher
from tests.helpers import ConfigFactory


class TestIssue6653FetchAllGraphqlNoSlashGuard:
    """_fetch_all_graphql raises an opaque ValueError when config.repo has no
    slash, instead of a descriptive error."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6653 — fix not yet landed", strict=False)
    async def test_fetch_all_graphql_empty_repo_raises_descriptive_error(
        self, config: HydraFlowConfig
    ) -> None:
        """_fetch_all_graphql must raise a clear ValueError with a message
        mentioning the expected 'owner/name' format when config.repo is empty.

        Currently FAILS because the raw ``str.split`` unpack raises
        ``ValueError: not enough values to unpack (expected 2, got 1)``
        with no mention of ``config.repo`` or the expected format.
        """
        cfg = ConfigFactory.create(
            repo="",
            repo_root=config.repo_root,
            workspace_base=config.workspace_base,
            state_file=config.state_file,
        )
        creds = Credentials(gh_token="test-token")
        fetcher = IssueFetcher(cfg, creds)

        with pytest.raises(ValueError, match=r"owner/name"):
            await fetcher._fetch_all_graphql(["hydraflow-ready"])

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6653 — fix not yet landed", strict=False)
    async def test_fetch_all_graphql_no_slash_repo_raises_descriptive_error(
        self, config: HydraFlowConfig
    ) -> None:
        """_fetch_all_graphql must raise a clear ValueError with a message
        mentioning the expected 'owner/name' format when config.repo has no
        slash (e.g. just a repo name without an owner).

        Currently FAILS because the raw ``str.split`` unpack raises
        ``ValueError: not enough values to unpack (expected 2, got 1)``
        with no mention of ``config.repo`` or the expected format.

        Note: HydraFlowConfig's Pydantic validator rejects non-empty repos
        without a slash, so we construct with a valid repo and then
        monkey-patch to simulate the misconfigured state reaching the
        GraphQL method.
        """
        cfg = ConfigFactory.create(
            repo="test-org/test-repo",
            repo_root=config.repo_root,
            workspace_base=config.workspace_base,
            state_file=config.state_file,
        )
        creds = Credentials(gh_token="test-token")
        fetcher = IssueFetcher(cfg, creds)
        # Simulate a misconfigured repo value reaching _fetch_all_graphql
        fetcher._config = cfg.model_copy(update={"repo": "just-a-repo-name"})

        with pytest.raises(ValueError, match=r"owner/name"):
            await fetcher._fetch_all_graphql(["hydraflow-ready"])
