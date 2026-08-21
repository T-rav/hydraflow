"""Regression for #11549: same-stage refreshes must replace queued metadata."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from events import EventBus
from issue_store import IssueStore
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory


@pytest.mark.asyncio
async def test_ready_claim_removal_unblocks_same_store_on_next_refresh() -> None:
    claimed = TaskFactory.create(
        id=11480,
        tags=["hydraflow-ready", "hydraflow-in-progress", "P1"],
    )
    released = claimed.model_copy(update={"tags": ["hydraflow-ready", "P1"]})
    fetcher = AsyncMock()
    fetcher.fetch_all = AsyncMock(side_effect=[[claimed], [released]])
    store = IssueStore(
        ConfigFactory.create(ready_label=["hydraflow-ready"]),
        fetcher,
        EventBus(),
    )

    await store.refresh()
    assert store.get_implementable(1) == []
    await store.refresh()

    assert store.get_implementable(1) == [released]
