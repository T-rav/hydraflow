"""Tests for the expert council voting system."""

from __future__ import annotations

import pytest

from expert_council import (
    DIVERSIFIED_EXPERTS,
    EXPERTS,
    CouncilResult,
    CouncilVote,
    ExpertCouncil,
)
from models import Task


class TestCouncilVote:
    def test_direction_uppercased(self) -> None:
        vote = CouncilVote("User Advocate", "b", "Good UX", 8)
        assert vote.direction == "B"

    def test_confidence_clamped(self) -> None:
        vote = CouncilVote("Expert", "A", "reason", 15)
        assert vote.confidence == 10
        vote2 = CouncilVote("Expert", "A", "reason", -5)
        assert vote2.confidence == 1

    def test_to_dict(self) -> None:
        vote = CouncilVote("Tech Lead", "C", "Feasible", 7)
        d = vote.to_dict()
        assert d["expert"] == "Tech Lead"
        assert d["direction"] == "C"
        assert d["confidence"] == 7


class TestCouncilResult:
    def test_consensus_with_2_of_3_agreeing(self) -> None:
        votes = [
            CouncilVote("User Advocate", "B", "Best UX", 8),
            CouncilVote("Tech Lead", "B", "Feasible", 7),
            CouncilVote("Strategist", "A", "Better market fit", 6),
        ]
        result = CouncilResult(votes)
        assert result.has_consensus is True
        assert result.winning_direction == "B"

    def test_no_consensus_with_3_way_split(self) -> None:
        votes = [
            CouncilVote("User Advocate", "A", "reason", 5),
            CouncilVote("Tech Lead", "B", "reason", 5),
            CouncilVote("Strategist", "C", "reason", 5),
        ]
        result = CouncilResult(votes)
        assert result.has_consensus is False
        assert result.winning_direction is None

    def test_unanimous_consensus(self) -> None:
        votes = [
            CouncilVote("User Advocate", "A", "reason", 9),
            CouncilVote("Tech Lead", "A", "reason", 8),
            CouncilVote("Strategist", "A", "reason", 7),
        ]
        result = CouncilResult(votes)
        assert result.has_consensus is True
        assert result.winning_direction == "A"
        assert result.avg_confidence == 8.0

    def test_format_summary_consensus(self) -> None:
        votes = [
            CouncilVote("User Advocate", "B", "Best UX", 8),
            CouncilVote("Tech Lead", "B", "Feasible", 7),
            CouncilVote("Strategist", "A", "Market fit", 6),
        ]
        result = CouncilResult(votes)
        summary = result.format_summary()
        assert "Expert Council Vote" in summary
        assert "Consensus reached" in summary
        assert "Direction B" in summary

    def test_format_summary_no_consensus(self) -> None:
        votes = [
            CouncilVote("User Advocate", "A", "reason", 5),
            CouncilVote("Tech Lead", "B", "reason", 5),
            CouncilVote("Strategist", "C", "reason", 5),
        ]
        result = CouncilResult(votes)
        summary = result.format_summary()
        assert "No consensus" in summary
        assert "tiebreaker" in summary


class TestParseVote:
    def test_parses_valid_vote(self) -> None:
        transcript = """Some preamble.

COUNCIL_VOTE_START

```json
{"direction": "B", "reasoning": "Great UX potential", "confidence": 8}
```

COUNCIL_VOTE_END
"""
        vote = ExpertCouncil._parse_vote(transcript, "User Advocate")
        assert vote is not None
        assert vote.direction == "B"
        assert vote.confidence == 8

    def test_returns_none_without_markers(self) -> None:
        vote = ExpertCouncil._parse_vote("no markers here", "Expert")
        assert vote is None

    def test_returns_none_with_bad_json(self) -> None:
        transcript = "COUNCIL_VOTE_START\n```json\n{bad}\n```\nCOUNCIL_VOTE_END"
        vote = ExpertCouncil._parse_vote(transcript, "Expert")
        assert vote is None


class TestDiversifiedExperts:
    """ADR-0063 W4 diversified-persona panel for round 3 council votes."""

    def test_panel_has_three_distinct_personas(self) -> None:
        """The W4 spec requires exactly three personas, each named distinctly."""
        names = [p["name"] for p in DIVERSIFIED_EXPERTS]
        assert len(DIVERSIFIED_EXPERTS) == 3
        assert len(set(names)) == 3
        assert "Dissenter" in names
        assert "Consensus-Seeker" in names
        assert "Regret-in-6-Months" in names

    def test_panel_distinct_from_standard_experts(self) -> None:
        """Diversified personas must not overlap with the standard panel — the
        whole point of round 3 is to bring different angles."""
        standard = {e["name"] for e in EXPERTS}
        diversified = {p["name"] for p in DIVERSIFIED_EXPERTS}
        assert standard.isdisjoint(diversified)

    def test_dissenter_perspective_mentions_arguing_against(self) -> None:
        dissenter = next(p for p in DIVERSIFIED_EXPERTS if p["name"] == "Dissenter")
        assert "against" in dissenter["perspective"].lower()

    def test_consensus_seeker_perspective_mentions_acceptability(self) -> None:
        seeker = next(p for p in DIVERSIFIED_EXPERTS if p["name"] == "Consensus-Seeker")
        text = seeker["perspective"].lower()
        # The persona's job is to find an option everyone can live with.
        assert "live with" in text or "common denominator" in text

    def test_regret_perspective_mentions_future_lookback(self) -> None:
        regret = next(
            p for p in DIVERSIFIED_EXPERTS if p["name"] == "Regret-in-6-Months"
        )
        assert "6 months" in regret["perspective"]


class TestVoteDiversified:
    """The ``vote_diversified`` method runs the W4 panel instead of EXPERTS."""

    @pytest.mark.asyncio
    async def test_vote_diversified_runs_each_diversified_persona(self) -> None:
        """``vote_diversified`` must dispatch one ``_run_expert`` per
        diversified persona, not per standard expert."""
        council = ExpertCouncil.__new__(ExpertCouncil)
        # Stub _run_expert to return a vote tagged with the expert's name so
        # we can verify which panel was dispatched.
        called_names: list[str] = []

        async def _fake_run_expert(
            task: Task, expert: dict, directions_text: str
        ) -> CouncilVote:
            called_names.append(expert["name"])
            return CouncilVote(expert["name"], "A", "test", 7)

        council._run_expert = _fake_run_expert  # type: ignore[assignment]
        task = Task(id=1, title="t", body="b", labels=[])

        result = await council.vote_diversified(task, "directions")

        assert called_names == [p["name"] for p in DIVERSIFIED_EXPERTS]
        assert len(result.votes) == 3

    @pytest.mark.asyncio
    async def test_vote_diversified_consensus_returns_winner(self) -> None:
        """Unanimous diversified-panel vote produces consensus on that
        direction — the round-3 happy path."""
        council = ExpertCouncil.__new__(ExpertCouncil)
        votes_to_return = ["B", "B", "B"]

        async def _fake_run_expert(
            task: Task, expert: dict, directions_text: str
        ) -> CouncilVote:
            return CouncilVote(expert["name"], votes_to_return.pop(0), "test", 8)

        council._run_expert = _fake_run_expert  # type: ignore[assignment]
        task = Task(id=1, title="t", body="b", labels=[])

        result = await council.vote_diversified(task, "directions")

        assert result.has_consensus is True
        assert result.winning_direction == "B"

    @pytest.mark.asyncio
    async def test_vote_diversified_split_returns_no_consensus(self) -> None:
        """If the diversified panel itself splits, that's a real escalation
        signal — the result must surface no consensus so the caller can
        escalate."""
        council = ExpertCouncil.__new__(ExpertCouncil)
        votes_to_return = ["A", "B", "C"]

        async def _fake_run_expert(
            task: Task, expert: dict, directions_text: str
        ) -> CouncilVote:
            return CouncilVote(expert["name"], votes_to_return.pop(0), "test", 5)

        council._run_expert = _fake_run_expert  # type: ignore[assignment]
        task = Task(id=1, title="t", body="b", labels=[])

        result = await council.vote_diversified(task, "directions")

        assert result.has_consensus is False
        assert result.winning_direction is None

    @pytest.mark.asyncio
    async def test_vote_diversified_tolerates_single_expert_failure(self) -> None:
        """A single persona crash must not disqualify the whole panel — the
        remaining votes still tally and ``reraise_on_credit_or_bug`` only
        propagates credit/bug exceptions."""
        council = ExpertCouncil.__new__(ExpertCouncil)
        # Make the first persona raise a generic Exception; others succeed.
        call_count = {"n": 0}

        async def _fake_run_expert(
            task: Task, expert: dict, directions_text: str
        ) -> CouncilVote:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("persona crashed")
            return CouncilVote(expert["name"], "A", "test", 6)

        council._run_expert = _fake_run_expert  # type: ignore[assignment]
        task = Task(id=1, title="t", body="b", labels=[])

        result = await council.vote_diversified(task, "directions")

        # 2/3 still constitutes the supermajority — consensus stands.
        assert len(result.votes) == 2
        assert result.has_consensus is True
        assert result.winning_direction == "A"


class TestVoteUsesStandardPanel:
    """The original ``vote`` method must still dispatch the standard panel,
    so adding diversified personas does not regress existing behavior."""

    @pytest.mark.asyncio
    async def test_vote_runs_each_standard_expert(self) -> None:
        council = ExpertCouncil.__new__(ExpertCouncil)
        called_names: list[str] = []

        async def _fake_run_expert(
            task: Task, expert: dict, directions_text: str
        ) -> CouncilVote:
            called_names.append(expert["name"])
            return CouncilVote(expert["name"], "A", "test", 7)

        council._run_expert = _fake_run_expert  # type: ignore[assignment]
        task = Task(id=1, title="t", body="b", labels=[])

        await council.vote(task, "directions")

        assert called_names == [e["name"] for e in EXPERTS]
