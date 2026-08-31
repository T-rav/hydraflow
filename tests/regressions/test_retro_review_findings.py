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
