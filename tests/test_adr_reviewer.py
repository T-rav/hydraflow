"""Tests for the ADRCouncilReviewer."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from adr_reviewer import ADRCouncilReviewer
from models import ADRCouncilResult, CouncilVerdict, CouncilVote
from tests.helpers import ConfigFactory


def _make_reviewer(
    tmp_path: Path,
    *,
    adr_review_enabled: bool = True,
    adr_review_approval_threshold: int = 2,
    adr_review_max_rounds: int = 3,
) -> ADRCouncilReviewer:
    """Build an ADRCouncilReviewer with test-friendly defaults."""
    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        adr_review_enabled=adr_review_enabled,
        adr_review_approval_threshold=adr_review_approval_threshold,
        adr_review_max_rounds=adr_review_max_rounds,
    )
    from events import EventBus

    bus = EventBus()
    prs = MagicMock()
    prs.create_issue = AsyncMock(return_value=42)
    runner = MagicMock()
    return ADRCouncilReviewer(config, bus, prs, runner)


def _write_adr(
    adr_dir: Path, number: int, title: str, status: str, decision: str = ""
) -> Path:
    """Write a sample ADR file."""
    adr_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{number:04d}-{title.lower().replace(' ', '-')}.md"
    path = adr_dir / filename
    content = f"""# ADR-{number:04d}: {title}

**Status:** {status}

## Context

Some context.

## Decision

{decision or "We decided to do the thing."}

## Consequences

Some consequences.
"""
    path.write_text(content, encoding="utf-8")
    return path


class TestFindProposedADRs:
    """Tests for _find_proposed_adrs."""

    def test_empty_dir(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        reviewer = _make_reviewer(tmp_path)
        assert reviewer._find_proposed_adrs(adr_dir) == []

    def test_finds_proposed_only(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        _write_adr(adr_dir, 1, "First ADR", "Proposed")
        _write_adr(adr_dir, 2, "Second ADR", "Accepted")
        _write_adr(adr_dir, 3, "Third ADR", "Proposed")
        reviewer = _make_reviewer(tmp_path)
        result = reviewer._find_proposed_adrs(adr_dir)
        assert len(result) == 2
        assert result[0][0] == 1
        assert result[1][0] == 3

    def test_filters_non_adr_files(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        _write_adr(adr_dir, 1, "Valid ADR", "Proposed")
        # Write a non-ADR file
        (adr_dir / "README.md").write_text("# ADRs\n\n**Status:** Proposed")
        reviewer = _make_reviewer(tmp_path)
        result = reviewer._find_proposed_adrs(adr_dir)
        assert len(result) == 1
        assert result[0][0] == 1

    def test_case_insensitive_status(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        _write_adr(adr_dir, 1, "First", "proposed")
        reviewer = _make_reviewer(tmp_path)
        result = reviewer._find_proposed_adrs(adr_dir)
        assert len(result) == 1


class TestDuplicateDetection:
    """Tests for _detect_duplicates."""

    def test_identical_titles(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        all_adrs = [
            (
                1,
                "use docker for isolation",
                "# Use Docker for Isolation\n\n## Decision\nUse Docker.",
            ),
            (
                2,
                "use docker for isolation",
                "# Use Docker for Isolation\n\n## Decision\nUse Docker containers.",
            ),
        ]
        content = "# Use Docker for Isolation\n\n## Decision\nUse Docker."
        result = reviewer._detect_duplicates(1, content, all_adrs)
        assert len(result) == 1
        assert result[0][0] == 2
        assert result[0][2] >= 0.7

    def test_different_adrs_no_duplicates(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        all_adrs = [
            (1, "use docker", "# Use Docker\n\n## Decision\nUse Docker."),
            (
                2,
                "adopt typescript",
                "# Adopt TypeScript\n\n## Decision\nSwitch to TypeScript.",
            ),
        ]
        content = "# Use Docker\n\n## Decision\nUse Docker."
        result = reviewer._detect_duplicates(1, content, all_adrs)
        assert len(result) == 0

    def test_self_exclusion(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        all_adrs = [
            (1, "use docker", "# Use Docker\n\n## Decision\nUse Docker."),
        ]
        content = "# Use Docker\n\n## Decision\nUse Docker."
        result = reviewer._detect_duplicates(1, content, all_adrs)
        assert len(result) == 0

    def test_threshold_boundary(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        all_adrs = [
            (1, "a", "# A\n\n## Decision\nX"),
            (
                2,
                "completely different thing entirely",
                "# Completely Different Thing Entirely\n\n## Decision\nY something else entirely different",
            ),
        ]
        content = "# A\n\n## Decision\nX"
        result = reviewer._detect_duplicates(1, content, all_adrs)
        # Titles "A" and "Completely Different Thing Entirely" should be below threshold
        assert len(result) == 0


class TestBuildOrchestratorPrompt:
    """Tests for _build_orchestrator_prompt."""

    def test_contains_role_instructions(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        prompt = reviewer._build_orchestrator_prompt("ADR content", "index", "no dupes")
        assert "Architect" in prompt
        assert "Pragmatist" in prompt
        assert "Editor" in prompt

    def test_contains_adr_content(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        prompt = reviewer._build_orchestrator_prompt(
            "My ADR content here", "index", "no dupes"
        )
        assert "My ADR content here" in prompt

    def test_contains_index_context(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        prompt = reviewer._build_orchestrator_prompt(
            "content", "ADR-0001: Test", "no dupes"
        )
        assert "ADR-0001: Test" in prompt

    def test_contains_duplicate_warnings(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        prompt = reviewer._build_orchestrator_prompt(
            "content", "index", "duplicate of 0013"
        )
        assert "duplicate of 0013" in prompt

    def test_injects_max_rounds(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path, adr_review_max_rounds=5)
        prompt = reviewer._build_orchestrator_prompt("content", "index", "none")
        assert "up to 5 rounds" in prompt

    def test_injects_approval_threshold(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path, adr_review_approval_threshold=3)
        prompt = reviewer._build_orchestrator_prompt("content", "index", "none")
        assert ">= 3 APPROVE" in prompt


class TestParseCouncilResult:
    """Tests for _parse_council_result."""

    def _make_transcript(
        self,
        *,
        rounds: int = 1,
        architect: str = "APPROVE",
        pragmatist: str = "APPROVE",
        editor: str = "APPROVE",
        final: str = "ACCEPT",
        duplicate_of: str = "none",
        summary: str = "All agreed.",
        minority: str = "none",
    ) -> str:
        return f"""Some preamble text.

COUNCIL_RESULT:
rounds_needed: {rounds}
architect_verdict: {architect}
architect_reasoning: Architect thinks this is good
pragmatist_verdict: {pragmatist}
pragmatist_reasoning: Pragmatist agrees
editor_verdict: {editor}
editor_reasoning: Editor is fine with it
approve_count: 3
reject_count: 0
final_decision: {final}
summary: {summary}
duplicate_of: {duplicate_of}
minority_note: {minority}

Some trailing text."""

    def test_parse_unanimous_approve(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        transcript = self._make_transcript()
        result = reviewer._parse_council_result(transcript, 1, "Test ADR")
        assert result.final_decision == "ACCEPT"
        assert result.rounds_needed == 1
        assert len(result.votes) == 3
        assert all(v.verdict == CouncilVerdict.APPROVE for v in result.votes)

    def test_parse_reject(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        transcript = self._make_transcript(
            architect="REJECT",
            pragmatist="REJECT",
            editor="REJECT",
            final="REJECT",
        )
        result = reviewer._parse_council_result(transcript, 1, "Test ADR")
        assert result.final_decision == "REJECT"
        assert all(v.verdict == CouncilVerdict.REJECT for v in result.votes)

    def test_parse_request_changes(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        transcript = self._make_transcript(
            architect="REQUEST_CHANGES",
            pragmatist="APPROVE",
            editor="REQUEST_CHANGES",
            final="REQUEST_CHANGES",
        )
        result = reviewer._parse_council_result(transcript, 1, "Test ADR")
        assert result.final_decision == "REQUEST_CHANGES"

    def test_parse_duplicate(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        transcript = self._make_transcript(
            architect="APPROVE",
            pragmatist="DUPLICATE",
            editor="APPROVE",
            final="DUPLICATE",
            duplicate_of="13",
        )
        result = reviewer._parse_council_result(transcript, 18, "Test ADR")
        assert result.duplicate_detected is True
        assert result.duplicate_of == 13
        assert result.final_decision == "DUPLICATE"

    def test_parse_multi_round(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        transcript = self._make_transcript(rounds=3)
        result = reviewer._parse_council_result(transcript, 1, "Test ADR")
        assert result.rounds_needed == 3
        assert len(result.all_round_votes) == 1  # Only final round in output block

    def test_missing_council_result_block(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = reviewer._parse_council_result("No result here", 1, "Test ADR")
        assert result.final_decision == "NO_CONSENSUS"

    def test_malformed_output_defaults_to_request_changes(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        transcript = """COUNCIL_RESULT:
rounds_needed: 1
architect_verdict: UNKNOWN_THING
pragmatist_verdict: ALSO_UNKNOWN
editor_verdict: NOPE
final_decision: SOMETHING_WEIRD
summary: unclear

"""
        result = reviewer._parse_council_result(transcript, 1, "Test")
        # Unknown final decision should map to NO_CONSENSUS
        assert result.final_decision == "NO_CONSENSUS"
        # Unknown verdicts map to REQUEST_CHANGES
        assert all(v.verdict == CouncilVerdict.REQUEST_CHANGES for v in result.votes)


class TestVerdictRouting:
    """Tests for _route_result."""

    @pytest.mark.asyncio
    async def test_approve_routes_to_accept(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            final_decision="ACCEPT",
            votes=[
                CouncilVote(role="architect", verdict=CouncilVerdict.APPROVE),
                CouncilVote(role="pragmatist", verdict=CouncilVerdict.APPROVE),
                CouncilVote(role="editor", verdict=CouncilVerdict.APPROVE),
            ],
        )
        stats = {"accepted": 0, "rejected": 0, "escalated": 0, "duplicates": 0}
        adr_path = tmp_path / "docs" / "adr" / "0001-test.md"
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        adr_path.write_text("**Status:** Proposed\n")

        with patch.object(
            reviewer, "_accept_adr", new_callable=AsyncMock
        ) as mock_accept:
            await reviewer._route_result(result, adr_path, adr_dir, stats)
            mock_accept.assert_awaited_once()
        assert stats["accepted"] == 1

    @pytest.mark.asyncio
    async def test_reject_routes_to_hitl(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            final_decision="REJECT",
        )
        stats = {"accepted": 0, "rejected": 0, "escalated": 0, "duplicates": 0}

        with patch.object(
            reviewer, "_escalate_to_hitl", new_callable=AsyncMock
        ) as mock_hitl:
            await reviewer._route_result(result, MagicMock(), MagicMock(), stats)
            mock_hitl.assert_awaited_once_with(result, reason="rejected")
        assert stats["rejected"] == 1

    @pytest.mark.asyncio
    async def test_request_changes_routes_to_hitl(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            final_decision="REQUEST_CHANGES",
        )
        stats = {"accepted": 0, "rejected": 0, "escalated": 0, "duplicates": 0}

        with patch.object(
            reviewer, "_escalate_to_hitl", new_callable=AsyncMock
        ) as mock_hitl:
            await reviewer._route_result(result, MagicMock(), MagicMock(), stats)
            mock_hitl.assert_awaited_once_with(result, reason="changes_requested")
        assert stats["escalated"] == 1

    @pytest.mark.asyncio
    async def test_duplicate_takes_priority(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=18,
            adr_title="Test",
            final_decision="ACCEPT",
            duplicate_detected=True,
            duplicate_of=13,
            votes=[
                CouncilVote(role="architect", verdict=CouncilVerdict.APPROVE),
                CouncilVote(
                    role="pragmatist", verdict=CouncilVerdict.DUPLICATE, duplicate_of=13
                ),
                CouncilVote(role="editor", verdict=CouncilVerdict.APPROVE),
            ],
        )
        stats = {"accepted": 0, "rejected": 0, "escalated": 0, "duplicates": 0}

        with patch.object(
            reviewer, "_handle_duplicate", new_callable=AsyncMock
        ) as mock_dup:
            await reviewer._route_result(result, MagicMock(), MagicMock(), stats)
            mock_dup.assert_awaited_once()
        assert stats["duplicates"] == 1
        assert stats["accepted"] == 0

    @pytest.mark.asyncio
    async def test_no_consensus_routes_to_hitl(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            final_decision="NO_CONSENSUS",
        )
        stats = {"accepted": 0, "rejected": 0, "escalated": 0, "duplicates": 0}

        with patch.object(
            reviewer, "_escalate_to_hitl", new_callable=AsyncMock
        ) as mock_hitl:
            await reviewer._route_result(result, MagicMock(), MagicMock(), stats)
            mock_hitl.assert_awaited_once_with(result, reason="no_consensus")
        assert stats["escalated"] == 1


class TestDeliberationRounds:
    """Tests for round count parsing and tracking."""

    def test_one_round_unanimous(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        transcript = """COUNCIL_RESULT:
rounds_needed: 1
architect_verdict: APPROVE
architect_reasoning: Good
pragmatist_verdict: APPROVE
pragmatist_reasoning: Fine
editor_verdict: APPROVE
editor_reasoning: Clear
approve_count: 3
reject_count: 0
final_decision: ACCEPT
summary: Unanimous
duplicate_of: none
minority_note: none

"""
        result = reviewer._parse_council_result(transcript, 1, "Test")
        assert result.rounds_needed == 1

    def test_two_round_convergence(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        transcript = """COUNCIL_RESULT:
rounds_needed: 2
architect_verdict: APPROVE
architect_reasoning: Changed mind
pragmatist_verdict: APPROVE
pragmatist_reasoning: Convinced
editor_verdict: APPROVE
editor_reasoning: Fine
approve_count: 3
reject_count: 0
final_decision: ACCEPT
summary: Converged in round 2
duplicate_of: none
minority_note: none

"""
        result = reviewer._parse_council_result(transcript, 1, "Test")
        assert result.rounds_needed == 2
        assert len(result.all_round_votes) == 1

    def test_three_round_deadlock(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        transcript = """COUNCIL_RESULT:
rounds_needed: 3
architect_verdict: APPROVE
architect_reasoning: Still approve
pragmatist_verdict: REJECT
pragmatist_reasoning: Still reject
editor_verdict: REQUEST_CHANGES
editor_reasoning: Still unsure
approve_count: 1
reject_count: 1
final_decision: REQUEST_CHANGES
summary: Deadlocked after 3 rounds
duplicate_of: none
minority_note: Architect wanted to approve but was outvoted

"""
        result = reviewer._parse_council_result(transcript, 1, "Test")
        assert result.rounds_needed == 3
        assert result.final_decision == "REQUEST_CHANGES"


class TestAcceptADR:
    """Tests for _accept_adr."""

    @pytest.mark.asyncio
    async def test_updates_status_in_file(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        adr_dir = tmp_path / "docs" / "adr"
        adr_path = _write_adr(adr_dir, 1, "Test ADR", "Proposed")
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test ADR",
            final_decision="ACCEPT",
            summary="Council approves",
            votes=[
                CouncilVote(
                    role="architect", verdict=CouncilVerdict.APPROVE, reasoning="Good"
                ),
            ],
        )

        with patch("adr_reviewer.run_subprocess", new_callable=AsyncMock):
            await reviewer._accept_adr(result, adr_path, adr_dir)

        content = adr_path.read_text(encoding="utf-8")
        assert "**Status:** Accepted" in content
        assert "**Status:** Proposed" not in content

    @pytest.mark.asyncio
    async def test_updates_readme_row(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        adr_dir = tmp_path / "docs" / "adr"
        adr_path = _write_adr(adr_dir, 1, "Test ADR", "Proposed")
        readme = adr_dir / "README.md"
        readme.write_text(
            "| Number | Title | Status |\n"
            "| 0001 | Test ADR | Proposed |\n"
            "| 0002 | Other | Accepted |\n"
        )
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test ADR",
            final_decision="ACCEPT",
            summary="Council approves",
            votes=[
                CouncilVote(
                    role="architect", verdict=CouncilVerdict.APPROVE, reasoning="Good"
                ),
            ],
        )

        with patch("adr_reviewer.run_subprocess", new_callable=AsyncMock):
            await reviewer._accept_adr(result, adr_path, adr_dir)

        readme_content = readme.read_text(encoding="utf-8")
        assert "Accepted" in readme_content.split("\n")[1]
        # Other rows unchanged
        assert "| 0002 | Other | Accepted |" in readme_content

    @pytest.mark.asyncio
    async def test_minority_note_included(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        adr_dir = tmp_path / "docs" / "adr"
        adr_path = _write_adr(adr_dir, 1, "Test ADR", "Proposed")
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test ADR",
            final_decision="ACCEPT",
            summary="Majority approves",
            minority_note="Editor had concerns about formatting",
            votes=[
                CouncilVote(
                    role="architect", verdict=CouncilVerdict.APPROVE, reasoning="Good"
                ),
                CouncilVote(
                    role="pragmatist", verdict=CouncilVerdict.APPROVE, reasoning="Fine"
                ),
                CouncilVote(
                    role="editor",
                    verdict=CouncilVerdict.REQUEST_CHANGES,
                    reasoning="Formatting",
                ),
            ],
        )

        mock_run = AsyncMock()
        with patch("adr_reviewer.run_subprocess", mock_run):
            await reviewer._accept_adr(result, adr_path, adr_dir)

        # Check commit message includes minority note
        commit_calls = [
            c
            for c in mock_run.await_args_list
            if c.args[0] == "git" and c.args[1] == "commit"
        ]
        assert len(commit_calls) == 1
        commit_msg = commit_calls[0].args[3]
        assert "Minority note:" in commit_msg


class TestEscalateToHITL:
    """Tests for _escalate_to_hitl."""

    @pytest.mark.asyncio
    async def test_creates_issue_with_summary(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=5,
            adr_title="Bad ADR",
            final_decision="REJECT",
            rounds_needed=2,
            summary="Council rejects this ADR",
            votes=[
                CouncilVote(
                    role="architect",
                    verdict=CouncilVerdict.REJECT,
                    reasoning="Too broad",
                ),
                CouncilVote(
                    role="pragmatist",
                    verdict=CouncilVerdict.REJECT,
                    reasoning="Not needed",
                ),
                CouncilVote(
                    role="editor",
                    verdict=CouncilVerdict.APPROVE,
                    reasoning="Well written",
                ),
            ],
        )

        await reviewer._escalate_to_hitl(result, reason="rejected")

        reviewer._prs.create_issue.assert_awaited_once()
        call_args = reviewer._prs.create_issue.await_args
        title = call_args.args[0]
        body = call_args.args[1]
        assert "ADR-0005" in title
        assert "rejection" in title.lower() or "reject" in title.lower()
        assert "Too broad" in body
        assert "Not needed" in body
        assert "Rounds needed" in body or "rounds_needed" in body.lower()

    @pytest.mark.asyncio
    async def test_reason_field_set_correctly(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1, adr_title="Test", final_decision="REQUEST_CHANGES"
        )

        await reviewer._escalate_to_hitl(result, reason="changes_requested")

        body = reviewer._prs.create_issue.await_args.args[1]
        assert "requests changes" in body.lower() or "changes" in body.lower()


class TestHandleDuplicate:
    """Tests for _handle_duplicate."""

    @pytest.mark.asyncio
    async def test_creates_duplicate_issue(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=18,
            adr_title="Duplicate Thing",
            final_decision="DUPLICATE",
            duplicate_detected=True,
            duplicate_of=13,
            votes=[
                CouncilVote(
                    role="editor",
                    verdict=CouncilVerdict.DUPLICATE,
                    duplicate_of=13,
                    reasoning="Same as ADR-13",
                ),
            ],
        )

        await reviewer._handle_duplicate(result)

        reviewer._prs.create_issue.assert_awaited_once()
        call_args = reviewer._prs.create_issue.await_args
        body = call_args.args[1]
        assert "0018" in body or "18" in body
        assert "0013" in body or "13" in body

    @pytest.mark.asyncio
    async def test_duplicate_of_populated(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=18,
            adr_title="Dup",
            final_decision="DUPLICATE",
            duplicate_detected=True,
            duplicate_of=13,
        )

        await reviewer._handle_duplicate(result)

        body = reviewer._prs.create_issue.await_args.args[1]
        assert "ADR-0013" in body


class TestBuildCouncilSummary:
    """Tests for _build_council_summary."""

    def test_multi_round_format(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            rounds_needed=2,
            final_decision="ACCEPT",
            summary="Converged after discussion",
            votes=[
                CouncilVote(
                    role="architect",
                    verdict=CouncilVerdict.APPROVE,
                    reasoning="Good structure",
                ),
                CouncilVote(
                    role="pragmatist",
                    verdict=CouncilVerdict.APPROVE,
                    reasoning="Practical",
                ),
                CouncilVote(
                    role="editor",
                    verdict=CouncilVerdict.APPROVE,
                    reasoning="Well written",
                ),
            ],
        )

        summary = reviewer._build_council_summary(result)
        assert "ACCEPT" in summary
        assert "2" in summary  # rounds_needed
        assert "Architect" in summary
        assert "Pragmatist" in summary
        assert "Editor" in summary
        assert "Good structure" in summary

    def test_minority_notes(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            final_decision="ACCEPT",
            minority_note="Editor had concerns",
            votes=[
                CouncilVote(
                    role="architect", verdict=CouncilVerdict.APPROVE, reasoning="OK"
                ),
            ],
        )

        summary = reviewer._build_council_summary(result)
        assert "Editor had concerns" in summary

    def test_per_judge_reasoning(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            final_decision="REJECT",
            votes=[
                CouncilVote(
                    role="architect",
                    verdict=CouncilVerdict.REJECT,
                    reasoning="Too narrow scope",
                ),
                CouncilVote(
                    role="pragmatist",
                    verdict=CouncilVerdict.REJECT,
                    reasoning="Already covered",
                ),
                CouncilVote(
                    role="editor",
                    verdict=CouncilVerdict.APPROVE,
                    reasoning="Clear prose",
                ),
            ],
        )

        summary = reviewer._build_council_summary(result)
        assert "Too narrow scope" in summary
        assert "Already covered" in summary
        assert "Clear prose" in summary


class TestReviewProposedADRs:
    """Integration-level tests for review_proposed_adrs."""

    @pytest.mark.asyncio
    async def test_no_adr_directory(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        stats = await reviewer.review_proposed_adrs()
        assert stats["reviewed"] == 0

    @pytest.mark.asyncio
    async def test_no_proposed_adrs(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        adr_dir = Path(reviewer._config.repo_root) / "docs" / "adr"
        _write_adr(adr_dir, 1, "Accepted ADR", "Accepted")
        stats = await reviewer.review_proposed_adrs()
        assert stats["reviewed"] == 0

    @pytest.mark.asyncio
    async def test_reviews_proposed_adrs(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        adr_dir = Path(reviewer._config.repo_root) / "docs" / "adr"
        _write_adr(adr_dir, 1, "Proposed ADR", "Proposed")

        accept_result = ADRCouncilResult(
            adr_number=1,
            adr_title="proposed adr",
            final_decision="ACCEPT",
            votes=[
                CouncilVote(role="architect", verdict=CouncilVerdict.APPROVE),
                CouncilVote(role="pragmatist", verdict=CouncilVerdict.APPROVE),
                CouncilVote(role="editor", verdict=CouncilVerdict.APPROVE),
            ],
        )
        with (
            patch.object(
                reviewer,
                "_run_council_session",
                new_callable=AsyncMock,
                return_value=accept_result,
            ),
            patch.object(reviewer, "_accept_adr", new_callable=AsyncMock),
        ):
            stats = await reviewer.review_proposed_adrs()

        assert stats["reviewed"] == 1
        assert stats["accepted"] == 1
