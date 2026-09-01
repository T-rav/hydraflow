"""#11890 — the retrospective loop reported patterns_filed: 0 for its whole life.

`_handle_retro_patterns` ran the analysis and then returned a hardcoded
``{"patterns_filed": 0}``, discarding whatever it filed. `_do_work` summed that
constant into the loop result, so every dashboard, vitals surface and operator
judgement reading the number was reading zero regardless of reality.

Behavioural: drives the loop with work that files something.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from retrospective_queue import QueueItem, QueueKind  # noqa: E402
from ports import PRPort


@pytest.mark.asyncio
async def test_filed_findings_reach_the_loop_result(retro_loop_factory):
    loop, collector = retro_loop_factory
    collector.analyze_evidence = AsyncMock(
        return_value={"signals": 4, "filed": 2, "policy": 1, "dropped": 3, "errors": 0}
    )

    result = await loop._process_item(
        QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=1)
    )

    assert result["patterns_filed"] == 2, (
        "the loop discarded the real count and reported a constant"
    )


@pytest.mark.asyncio
async def test_dropped_findings_are_surfaced_not_hidden(retro_loop_factory):
    """A confabulating model must show up as a rising drop rate."""
    loop, collector = retro_loop_factory
    collector.analyze_evidence = AsyncMock(
        return_value={"signals": 9, "filed": 0, "policy": 0, "dropped": 7, "errors": 0}
    )

    result = await loop._process_item(
        QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=1)
    )

    assert result["findings_dropped"] == 7


@pytest.fixture
def retro_loop_factory(tmp_path):
    from retrospective_loop import RetrospectiveLoop
    from tests.helpers import make_bg_loop_deps

    deps = make_bg_loop_deps(tmp_path, enabled=True)
    collector = MagicMock()
    collector._load_recent = MagicMock(return_value=[])
    loop = RetrospectiveLoop(
        config=deps.config,
        deps=deps.loop_deps,
        retrospective=collector,
        insights=MagicMock(),
        queue=MagicMock(),
        prs=MagicMock(spec=PRPort),
    )
    return loop, collector
