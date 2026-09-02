"""Regression: a response that yields no findings at all is counted (#11978).

`parse_findings` returned `[], 0` when `_extract_array` found no JSON array —
prose, a truncated fence, an apology. Zero drops is indistinguishable from a
model that correctly reported nothing, which is the exact silence the
function's own docstring promises not to keep.

It survived because the per-ITEM count beneath it was already correct (#11903),
so the counter existed and looked implemented while the path that loses the
most returned nothing.

The full case table lives in `tests/test_retro_finder.py`; this pins the shape
the defect took, and the second test pins the staleness found beside it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from retro_finder import RetroFinder, parse_findings  # noqa: E402
from retro_signals import EvidenceRef, RetroSignal  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.helpers import ConfigFactory  # noqa: E402

SIGNAL = RetroSignal(
    id="tool_error-abc1234567",
    family="tool_error",
    signature="Bash: make quality failed",
    count=7,
    issues=[1],
    evidence=[EvidenceRef(locator="traces/1/x", excerpt="make: *** [quality] Error 1")],
)


def test_a_response_with_no_parseable_array_is_counted_as_a_drop() -> None:
    findings, dropped = parse_findings("I could not find anything useful.")

    assert findings == []
    assert dropped > 0, (
        "a tick whose model returned nothing parseable reported zero drops, "
        "which a reader cannot tell from a tick that correctly found nothing"
    )


@pytest.mark.asyncio
async def test_an_empty_response_does_not_inherit_the_previous_tick_count(
    tmp_path,
) -> None:
    """The early `if not raw: return []` skipped `parse_findings` entirely."""
    finder = RetroFinder(
        ConfigFactory.create(repo_root=tmp_path), AsyncMock(), MagicMock(gh_token="")
    )
    finder.unparseable = 3

    with patch.object(RetroFinder, "_call_model", new=AsyncMock(return_value="")):
        await finder.find([SIGNAL])

    assert finder.unparseable == 0, (
        "a tick that got no response at all published the previous tick's drops"
    )
