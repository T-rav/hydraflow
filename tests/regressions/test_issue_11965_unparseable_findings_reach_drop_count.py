"""#11965 — a confabulating model was invisible to the loop's drop rate.

#11903 pass two taught ``RetroFinder`` to count findings that failed to parse
(``self.unparseable``) instead of discarding them at debug level, and taught
``RetrospectiveCollector.analyze_evidence`` to read that count into
``counts["unparseable"]``. But nothing ever folded it into
``counts["dropped"]`` — the only key ``RetrospectiveLoop._handle_retro_patterns``
reads into the externally visible ``findings_dropped``. A tick where the model
returned nothing parseable (empty/malformed JSON, or items that failed Pydantic
validation) still reported ``findings_dropped: 0``, identical to a tick that
legitimately found nothing — exactly the confusion ADR-0144 says the drop-and-
count design exists to prevent ("a confabulating model shows up as a rising
drop rate rather than as board spam").

Also covers ``retro_finder.parse_findings``: a raw response with no JSON array
at all (full confabulation, prose instead of the requested shape) used to
count as zero unparseable findings rather than one.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from retro_signals import EvidenceRef, RetroSignal  # noqa: E402
from retrospective import RetrospectiveCollector, RetrospectiveEntry  # noqa: E402
from tests.helpers import ConfigFactory  # noqa: E402

SIGNAL = RetroSignal(
    id="tool_error-abc1234567",
    family="tool_error",
    signature="Bash: make quality failed",
    count=7,
    issues=[1],
    evidence=[EvidenceRef(locator="traces/1/x", excerpt="make: *** [quality] Error 1")],
)


def _entry(n: int) -> RetrospectiveEntry:
    return RetrospectiveEntry(
        issue_number=n, pr_number=n + 100, timestamp="2026-08-31T00:00:00+00:00"
    )


def _collector(tmp_path: Path) -> RetrospectiveCollector:
    config = ConfigFactory.create()
    config.data_root = tmp_path / "data"
    config.repo_root = tmp_path
    prs = MagicMock()
    prs.get_issue_labels = AsyncMock(return_value=[])
    return RetrospectiveCollector(config, MagicMock(), prs)


class TestUnparseableFindingsReachTheDropCount:
    @pytest.mark.asyncio
    async def test_a_fully_confabulating_response_raises_the_drop_count(
        self, tmp_path: Path
    ):
        """The finder saw signals but produced nothing usable — must not read as zero drops."""
        collector = _collector(tmp_path)

        async def _find(self, *_args, **_kwargs):  # noqa: ANN001
            self.unparseable = 3
            return []

        with (
            patch("retrospective.extract", return_value=[SIGNAL]),
            patch("retro_finder.RetroFinder.find", new=_find),
        ):
            counts = await collector.analyze_evidence([_entry(1)])

        assert counts["dropped"] == 3, (
            "unparseable model output vanished instead of raising the drop rate"
        )
        assert counts["filed"] == 0

    @pytest.mark.asyncio
    async def test_parse_and_anchor_drops_both_count_toward_the_same_total(
        self, tmp_path: Path
    ):
        from retro_findings import GateFinding

        collector = _collector(tmp_path)
        hallucinated = GateFinding(
            kind="gate",
            signal_id=SIGNAL.id,
            title="Guard repeated quality failures",
            guard_path="src/invented.py",
            observed="7 occurrences",
        )

        async def _find(self, *_args, **_kwargs):  # noqa: ANN001
            self.unparseable = 2
            return [hallucinated]

        with (
            patch("retrospective.extract", return_value=[SIGNAL]),
            patch("retro_finder.RetroFinder.find", new=_find),
        ):
            counts = await collector.analyze_evidence([_entry(1)])

        assert counts["dropped"] == 3, "one anchor-validation drop plus two parse drops"


class TestParseFindingsCountsTotalConfabulation:
    def test_a_response_with_no_json_array_counts_as_one_unparseable(self):
        """Previously: no array found -> (findings=[], unparseable=0), same as 'nothing to report'."""
        from retro_finder import parse_findings

        findings, unparseable = parse_findings("Sorry, I don't see any issues here.")

        assert findings == []
        assert unparseable == 1
