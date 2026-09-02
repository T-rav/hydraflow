"""#11856 — an unanchored goal reaches a human.

The last acceptance criterion of the Purpose ruling: goal referential integrity
is decided in the seam, and something has to ACT on the verdict. A decision
nobody actuates is the same as no decision.

Actuation lives in `CharterDriftCaretakerLoop`; the JUDGEMENT stays in
`PythonDecisionEngine`. The loop never re-derives a verdict, exactly as
`AdrConformanceLoop` acts on `decision.remediation` without re-classifying —
keeping the two apart is what lets a second engine be parity-tested against the
first (ADR-0143 Ruling 4).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from charter_drift_caretaker_loop import CharterDriftCaretakerLoop
from policy.models import DecisionStatus, StandardDecision


def _decision(subject: str, status: DecisionStatus) -> StandardDecision:
    return StandardDecision(
        standard="purpose",
        subject=subject,
        status=status,
        blocking=False,
        reason=f"goal '{subject}' is cited by nothing",
    )


def _loop(decisions, *, repo: str = "o/r"):
    loop = MagicMock(spec=CharterDriftCaretakerLoop)
    loop._config = MagicMock()
    loop._config.repo = repo
    loop._prs = MagicMock()
    loop._prs.create_issue = AsyncMock(return_value=4242)
    loop._purpose_auditor = AsyncMock(return_value=decisions)
    return loop


class TestAnUnanchoredGoalIsFiled:
    @pytest.mark.asyncio
    async def test_one_issue_per_unanchored_goal(self) -> None:
        # Per GOAL, not per repo: each is independently fixable — cite it or
        # drop it — and folding three into one issue makes closing it ambiguous.
        loop = _loop(
            [
                _decision("a_goal", DecisionStatus.VIOLATED),
                _decision("b_goal", DecisionStatus.VIOLATED),
            ]
        )

        filed = await CharterDriftCaretakerLoop._file_unanchored_goals(loop, set())

        assert filed == 2
        assert loop._prs.create_issue.await_count == 2

    @pytest.mark.asyncio
    async def test_the_issue_names_the_goal_and_both_ways_to_close_it(self) -> None:
        loop = _loop([_decision("a_goal", DecisionStatus.VIOLATED)])

        await CharterDriftCaretakerLoop._file_unanchored_goals(loop, set())

        title, body, *_ = loop._prs.create_issue.await_args.args
        assert "a_goal" in title
        assert "Cite it" in body
        assert "Drop it" in body

    @pytest.mark.asyncio
    async def test_a_compliant_goal_files_nothing(self) -> None:
        # The decoy. A loop that filed on every decision would satisfy the
        # tests above while opening an issue for every goal that IS cited.
        loop = _loop([_decision("a_goal", DecisionStatus.COMPLIANT)])

        filed = await CharterDriftCaretakerLoop._file_unanchored_goals(loop, set())

        assert filed == 0
        loop._prs.create_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_same_goal_is_not_filed_twice(self) -> None:
        loop = _loop([_decision("a_goal", DecisionStatus.VIOLATED)])
        dedup: set[str] = set()

        await CharterDriftCaretakerLoop._file_unanchored_goals(loop, dedup)
        again = await CharterDriftCaretakerLoop._file_unanchored_goals(loop, dedup)

        assert again == 0
        assert loop._prs.create_issue.await_count == 1

    @pytest.mark.asyncio
    async def test_a_failed_audit_does_not_break_the_tick(self) -> None:
        """Drift reporting must survive a purpose audit that cannot run.

        This is an additive concern on an existing loop; a broken read here
        must not cost the charter-drift findings the tick already produced.
        """
        loop = _loop([])
        loop._purpose_auditor = AsyncMock(side_effect=RuntimeError("unreadable"))

        assert await CharterDriftCaretakerLoop._file_unanchored_goals(loop, set()) == 0

    @pytest.mark.asyncio
    async def test_no_auditor_wired_is_a_no_op(self) -> None:
        # The collaborator is optional so every existing construction site and
        # test double keeps working untouched.
        loop = _loop([])
        loop._purpose_auditor = None

        assert await CharterDriftCaretakerLoop._file_unanchored_goals(loop, set()) == 0


class TestTheJudgementStaysInTheSeam:
    @pytest.mark.asyncio
    async def test_the_loop_reads_status_and_never_recomputes_it(self) -> None:
        """A VIOLATED decision files even when its reason says nothing useful.

        The loop must act on the typed verdict, not re-derive one from the
        reason text — that is what keeps a second engine parity-testable.
        """
        decision = StandardDecision(
            standard="purpose",
            subject="a_goal",
            status=DecisionStatus.VIOLATED,
            blocking=False,
            reason="",
        )

        filed = await CharterDriftCaretakerLoop._file_unanchored_goals(
            _loop([decision]), set()
        )

        assert filed == 1


class TestTheTickActuallyCallsIt:
    """The call site. Pinning the method alone leaves the wiring unguarded.

    A first pass had exactly that hole: deleting the call from `_do_work` kept
    every test above green, because the method was correct and unreached. It is
    the recurring failure of this session, so it gets its own test.
    """

    @pytest.mark.asyncio
    async def test_a_tick_files_the_unanchored_goal(self) -> None:
        from charter import CharterDriftReport

        loop = MagicMock(spec=CharterDriftCaretakerLoop)
        loop._enabled_cb = lambda _name: True
        loop._worker_name = "charter_drift_caretaker"
        loop._config = MagicMock()
        loop._config.charter_drift_caretaker_loop_enabled = True
        loop._config.dry_run = False
        loop._config.repo = "o/r"
        loop._auditor = AsyncMock(
            return_value=[CharterDriftReport(repo="o/r", findings=())]
        )
        loop._dedup = MagicMock()
        loop._dedup.get.return_value = set()
        loop._prs = MagicMock()
        loop._prs.create_issue = AsyncMock(return_value=4242)
        loop._purpose_auditor = AsyncMock(
            return_value=[_decision("a_goal", DecisionStatus.VIOLATED)]
        )
        loop._file_repo_drift = AsyncMock(return_value=(0, 0))
        loop._reconcile_resolved = AsyncMock(return_value=0)
        loop._file_unanchored_goals = (
            CharterDriftCaretakerLoop._file_unanchored_goals.__get__(loop)
        )

        result = await CharterDriftCaretakerLoop._do_work(loop)

        assert loop._prs.create_issue.await_count == 1
        assert result["filed"] == 1
