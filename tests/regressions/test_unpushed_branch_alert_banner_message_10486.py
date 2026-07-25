"""Regression #10486: unpushed_local_branches SYSTEM_ALERT rendered an empty banner.

``check_and_alert_unpushed_branches`` published a ``SYSTEM_ALERT`` carrying
only ``kind``/``branches``/``detail`` — never ``message`` or ``severity``.
The dashboard banner (``SystemAlertBanner`` in ``src/ui/src/App.jsx``) renders
``alert.message``, so the missing field produced a red (critical-by-default)
banner with no text on every boot where a local branch sat committed but
unpushed — a benign, informational condition rendered as an unexplained
critical alert.

Guards: the published payload must always carry a non-empty ``message`` (the
field the banner actually renders) and ``severity: "warning"`` (yellow, not
the red default) for this alert kind.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from branch_gc_scan import UnpushedBranch
from config import HydraFlowConfig
from events import EventBus, EventType
from unpushed_branch_alert import check_and_alert_unpushed_branches


async def test_unpushed_branches_alert_has_nonempty_message_and_warning_severity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = [
        UnpushedBranch(branch="fix-thing", upstream="origin/fix-thing", ahead=2)
    ]
    monkeypatch.setattr(
        "unpushed_branch_alert.scan_unpushed_local_branches",
        AsyncMock(return_value=found),
    )
    bus = EventBus()
    published = []
    bus.publish = AsyncMock(side_effect=published.append)  # type: ignore[method-assign]
    config = HydraFlowConfig(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        repo="owner/repo",
    )

    await check_and_alert_unpushed_branches(config, bus)

    assert len(published) == 1
    event = published[0]
    assert event.type == EventType.SYSTEM_ALERT
    # This is the field the dashboard banner renders — an absent/empty
    # message is the exact empty-red-banner symptom from #10486.
    assert event.data.get("message"), "SYSTEM_ALERT must carry a non-empty message"
    assert "fix-thing" in event.data["message"]
    # Committed-but-unpushed work is informational, not critical -> yellow.
    assert event.data.get("severity") == "warning"
