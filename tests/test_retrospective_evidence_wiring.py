"""The retrospective runs on evidence, not on PR metadata alone (§6).

Retires four hardcoded prose branches whose entire vocabulary was "consider
strengthening the implementation prompt", and replaces them with the
trace-grounded pipeline: gather → signals → finder → validate → emit.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from retro_findings import GateFinding  # noqa: E402
from retro_signals import EvidenceRef, RetroSignal  # noqa: E402
from retrospective import RetrospectiveCollector, RetrospectiveEntry  # noqa: E402
from tests.helpers import ConfigFactory  # noqa: E402

SIGNAL = RetroSignal(
    id="tool_error-abc1234567",
    family="tool_error",
    signature="Bash: make quality failed",
    count=7,
    issues=[1, 2],
    evidence=[EvidenceRef(locator="traces/1/x", excerpt="make: *** [quality] Error 1")],
)
FINDING = GateFinding(
    kind="gate",
    signal_id=SIGNAL.id,
    title="Guard repeated quality failures",
    guard_path="tests/architecture/test_q.py",
    observed="7 occurrences",
)


def _entry(n: int) -> RetrospectiveEntry:
    return RetrospectiveEntry(
        issue_number=n, pr_number=n + 100, timestamp="2026-08-31T00:00:00+00:00"
    )


def _collector(tmp_path: Path):
    config = ConfigFactory.create()
    config.data_root = tmp_path / "data"
    config.repo_root = tmp_path
    prs = MagicMock()
    prs.get_issue_labels = AsyncMock(return_value=["data-class:internal"])
    return RetrospectiveCollector(config, MagicMock(), prs), config


class TestTheProsePatternsAreGone:
    """Their entire output was advice with no file, command, error or guard."""

    @pytest.mark.parametrize(
        "attr",
        ["_detect_patterns", "_file_improvement_issue", "_load_filed_patterns"],
    )
    def test_retired_machinery_is_absent(self, tmp_path: Path, attr: str):
        collector, _ = _collector(tmp_path)

        assert not hasattr(collector, attr)


class TestEvidenceAnalysis:
    @pytest.mark.asyncio
    async def test_no_entries_files_nothing(self, tmp_path: Path):
        collector, _ = _collector(tmp_path)

        counts = await collector.analyze_evidence([])

        assert counts["filed"] == 0
        assert counts["signals"] == 0

    @pytest.mark.asyncio
    async def test_no_signals_short_circuits_before_the_model(self, tmp_path: Path):
        collector, _ = _collector(tmp_path)
        with patch("retro_finder.RetroFinder.find", new=AsyncMock()) as find:
            counts = await collector.analyze_evidence([_entry(1)])

        find.assert_not_awaited()
        assert counts["signals"] == 0

    @pytest.mark.asyncio
    async def test_signals_flow_through_finder_validator_and_emitter(
        self, tmp_path: Path
    ):
        collector, _ = _collector(tmp_path)
        (tmp_path / "tests" / "architecture").mkdir(parents=True)
        with (
            patch("retrospective.extract", return_value=[SIGNAL]),
            patch(
                "retro_finder.RetroFinder.find", new=AsyncMock(return_value=[FINDING])
            ),
            patch("retro_emitter.file_or_fold", new=AsyncMock(return_value=55)) as fof,
        ):
            counts = await collector.analyze_evidence([_entry(1), _entry(2)])

        assert counts["signals"] == 1
        assert counts["filed"] == 1
        assert fof.await_count == 1

    @pytest.mark.asyncio
    async def test_unresolvable_findings_are_dropped_and_counted(self, tmp_path: Path):
        collector, _ = _collector(tmp_path)
        hallucinated = FINDING.model_copy(update={"guard_path": "src/invented.py"})
        with (
            patch("retrospective.extract", return_value=[SIGNAL]),
            patch(
                "retro_finder.RetroFinder.find",
                new=AsyncMock(return_value=[hallucinated]),
            ),
            patch("retro_emitter.file_or_fold", new=AsyncMock(return_value=1)) as fof,
        ):
            counts = await collector.analyze_evidence([_entry(1)])

        assert counts["dropped"] == 1
        assert counts["filed"] == 0
        fof.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_issue_labels_are_unioned_across_the_window(self, tmp_path: Path):
        """CH-6 elevation must see every issue whose evidence was read."""
        collector, _ = _collector(tmp_path)
        collector._prs.get_issue_labels = AsyncMock(
            side_effect=[["data-class:public"], ["data-class:secret"]]
        )
        find = AsyncMock(return_value=[])
        with (
            patch("retrospective.extract", return_value=[SIGNAL]),
            patch("retro_finder.RetroFinder.find", new=find),
        ):
            await collector.analyze_evidence([_entry(1), _entry(2)])

        assert set(find.await_args.kwargs["issue_labels"]) == {
            "data-class:public",
            "data-class:secret",
        }

    @pytest.mark.asyncio
    async def test_label_lookup_failure_does_not_sink_the_analysis(
        self, tmp_path: Path
    ):
        collector, _ = _collector(tmp_path)
        collector._prs.get_issue_labels = AsyncMock(side_effect=OSError("offline"))
        find = AsyncMock(return_value=[])
        with (
            patch("retrospective.extract", return_value=[SIGNAL]),
            patch("retro_finder.RetroFinder.find", new=find),
        ):
            counts = await collector.analyze_evidence([_entry(1)])

        assert counts["signals"] == 1
        assert find.await_args.kwargs["issue_labels"] == []
