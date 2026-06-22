"""Regression #9602: list_issues_by_label and list_closed_issues_by_label must not raise
ValueError when gh returns empty stdout.

Root cause: `parse_list_with_shape("")` raises ValueError for empty input, which
`reraise_on_credit_or_bug` re-raises (ValueError is in LIKELY_BUG_EXCEPTIONS).
In `_reconcile_closed_escalations`, this propagated uncaught to `_execute_cycle`,
which reported the tick as an error (tick_error_ratio breach).

Fix: use `output or "[]"` before passing to `parse_list_with_shape`, matching the
pattern already used by other callers in pr_manager.py (line 2713).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from config import HydraFlowConfig
from events import EventBus
from pr_manager import PRManager


def _make_pr_manager(tmp_path: Path) -> PRManager:
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    creds = MagicMock()
    creds.gh_token = "tok"
    return PRManager(config=cfg, event_bus=EventBus(), credentials=creds)


@pytest.mark.asyncio
async def test_list_closed_issues_by_label_empty_gh_output(tmp_path: Path) -> None:
    """Empty stdout from gh must return [] rather than raising ValueError."""
    pr = _make_pr_manager(tmp_path)

    with patch.object(pr, "_run_gh", new=AsyncMock(return_value="")):
        result = await pr.list_closed_issues_by_label("principles-stuck", limit=100)

    assert result == []


@pytest.mark.asyncio
async def test_list_issues_by_label_empty_gh_output(tmp_path: Path) -> None:
    """Empty stdout from gh must return [] rather than raising ValueError."""
    pr = _make_pr_manager(tmp_path)

    with patch.object(pr, "_run_gh", new=AsyncMock(return_value="")):
        result = await pr.list_issues_by_label("principles-drift")

    assert result == []
