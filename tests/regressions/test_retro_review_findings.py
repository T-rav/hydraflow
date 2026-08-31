"""Self-review findings on the shipped retrospective (#11887/#11894/#11896).

Three defects the merged code carried, none caught by its own 78 tests:

1. The `observed` count check was a SUBSTRING test, so `count=7` was satisfied
   by "took 70 seconds" and `count=2` by any 2026 date. It is the only thing
   forcing a GATE finding to be quantified, and ADR-0144 claims it "must
   literally restate the signal's count".
2. `gather` read every transcript fully into memory and nothing consumed them —
   `extract` reads only `bundle.traces`. Unbounded reads for discarded data.
3. `_rejection_reason` fell through to policy validation for any unrecognised
   finding kind.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from retro_evidence import MAX_TRANSCRIPT_CHARS, gather  # noqa: E402
from retro_findings import GateFinding, validate  # noqa: E402
from retro_signals import EvidenceRef, RetroSignal  # noqa: E402
from tests.helpers import ConfigFactory  # noqa: E402

SIGNAL = RetroSignal(
    id="tool_error-abc1234567",
    family="tool_error",
    signature="Bash: make quality failed",
    count=7,
    issues=[1],
    evidence=[EvidenceRef(locator="l", excerpt="boom")],
)


def _gate(observed: str) -> GateFinding:
    return GateFinding(
        kind="gate",
        signal_id=SIGNAL.id,
        title="t",
        guard_path="tests/architecture/test_q.py",
        observed=observed,
    )


class TestObservedMustRestateTheCountNotMerelyContainItsDigits:
    @pytest.mark.parametrize(
        "observed",
        ["took 70 seconds", "17 unrelated things", "occurred 777 times"],
        ids=["substring-of-larger", "suffix-of-larger", "repeated-digit"],
    )
    def test_a_number_that_merely_contains_the_digits_is_dropped(
        self, observed: str, tmp_path: Path
    ):
        kept, dropped = validate([_gate(observed)], [SIGNAL], tmp_path)

        assert kept == []
        assert "count" in dropped[0].reason

    @pytest.mark.parametrize(
        "observed",
        ["7 occurrences", "seen 7 times across 1 issue", "count: 7"],
        ids=["bare", "sentence", "labelled"],
    )
    def test_a_genuine_restatement_is_kept(self, observed: str, tmp_path: Path):
        kept, _ = validate([_gate(observed)], [SIGNAL], tmp_path)

        assert len(kept) == 1


class TestTranscriptReadsAreBounded:
    def test_a_huge_transcript_is_truncated_not_slurped(self, tmp_path: Path):
        config = ConfigFactory.create()
        config.data_root = tmp_path / "data"
        config.log_dir.mkdir(parents=True, exist_ok=True)
        huge = "E" * (MAX_TRANSCRIPT_CHARS * 3)
        (config.log_dir / "issue-42.txt").write_text(huge)

        bundle = gather(config, 42)

        assert len(bundle.transcripts["issue-42"]) <= MAX_TRANSCRIPT_CHARS

    def test_the_tail_is_kept_because_failures_land_at_the_end(self, tmp_path: Path):
        config = ConfigFactory.create()
        config.data_root = tmp_path / "data"
        config.log_dir.mkdir(parents=True, exist_ok=True)
        (config.log_dir / "issue-42.txt").write_text(
            "A" * (MAX_TRANSCRIPT_CHARS * 2) + "THE-ACTUAL-ERROR"
        )

        bundle = gather(config, 42)

        assert bundle.transcripts["issue-42"].endswith("THE-ACTUAL-ERROR")


class TestUnknownKindsAreRejectedNotPolicyValidated:
    def test_an_unrecognised_finding_kind_is_dropped(self, tmp_path: Path):
        """A fourth kind must declare its own checks, not inherit policy's.

        Modelled as a sibling of the three real kinds — NOT a subclass of one,
        which would legitimately match that kind's isinstance branch.
        """

        class TelepathyFinding(BaseModel):
            kind: str = "telepathy"
            signal_id: str = SIGNAL.id
            title: str = "read the maintainer's mind"
            rationale: str = ""

        kept, dropped = validate([TelepathyFinding()], [SIGNAL], tmp_path)

        assert kept == []
        assert "kind" in dropped[0].reason


class TestPassTwoFindings:
    """Second review iteration over the modules pass one did not reach."""

    @pytest.mark.asyncio
    async def test_a_prompt_gate_block_escalates_instead_of_warning_forever(self):
        """A gate block is permanent — every call re-blocks (#9734 finding 3).

        A soft warn makes the finder a PERMANENT SILENT NO-OP. transcript_summarizer
        already escalates this exact case; the finder must too.
        """
        from unittest.mock import AsyncMock, patch

        from retro_finder import RetroFinder
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create()
        config.retro_finder_enabled = True
        blocked = type("R", (), {"returncode": 1, "stdout": "", "stderr": "prompt gate blocked: data-class"})()

        with (
            patch("runner_utils.run_lightweight_agent", new=AsyncMock(return_value=blocked)),
            patch("retro_finder.is_prompt_gate_blocked", return_value=True),
            patch("retro_finder.alert_prompt_gate_block", new=AsyncMock()) as alert,
        ):
            findings = await RetroFinder(config).find([SIGNAL])

        assert findings == []
        alert.assert_awaited_once()

    def test_findings_dropped_at_parse_time_are_counted_not_silent(self):
        """Otherwise a malformed model looks identical to 'nothing to report'."""
        import json

        from retro_finder import parse_findings

        payload = json.dumps(
            [
                {"kind": "gate", "signal_id": SIGNAL.id, "title": "t",
                 "guard_path": "tests/architecture/x.py", "observed": "7"},
                {"kind": "gate", "signal_id": SIGNAL.id, "title": "no anchor"},
                {"kind": "telepathy"},
            ]
        )

        findings, unparseable = parse_findings(payload)

        assert len(findings) == 1
        assert unparseable == 2

    @pytest.mark.asyncio
    async def test_findings_beyond_the_per_tick_cap_are_counted(self):
        """The cap must not silently discard the remainder."""
        from unittest.mock import AsyncMock, patch

        from retro_emitter import emit
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create()
        config.retro_findings_max_per_tick = 2
        findings = [_gate("7 occurrences") for _ in range(5)]

        with patch("retro_emitter.file_or_fold", new=AsyncMock(return_value=1)):
            counts = await emit(findings, [SIGNAL], object(), config)

        assert counts["filed"] == 2
        assert counts["capped"] == 3

    @pytest.mark.asyncio
    async def test_labels_are_not_fetched_when_the_finder_is_disabled(self, tmp_path):
        """10 GitHub calls per tick for a spawn that will not happen."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from retrospective import RetrospectiveCollector, RetrospectiveEntry
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create()
        config.data_root = tmp_path / "d"
        config.repo_root = tmp_path
        config.retro_finder_enabled = False
        prs = MagicMock()
        prs.get_issue_labels = AsyncMock(return_value=[])
        collector = RetrospectiveCollector(config, MagicMock(), prs)

        with patch("retrospective.extract", return_value=[SIGNAL]):
            await collector.analyze_evidence(
                [RetrospectiveEntry(issue_number=n, pr_number=n,
                                    timestamp="2026-08-31T00:00:00+00:00")
                 for n in range(1, 11)]
            )

        prs.get_issue_labels.assert_not_awaited()
