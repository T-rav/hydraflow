"""Regression pins for #11614 — the pipeline ignored ``Blocked by: #N``.

The bug: issue bodies declared dependencies as ``Blocked by: #N[, #M]`` and
nothing in the pipeline read them. A phase-ordered epic therefore decomposed
into children that ALL became eligible at once — on the live board, epics
#11531/#11532 put 11 children at once stage, of which only #11533 was
genuinely unblocked. With three implement workers, P3 and P6 would be built
before P0 existed, and those phases touch the same subsystems.

Pins:
1. Triage consults the declaration: a child whose blocker is OPEN is held
   before the LLM ever runs.
2. The hold is self-healing — no park label, no comment, nothing that needs a
   second actor to undo. A closed blocker simply lets the child through.
3. Fail-open. An unreadable blocker must NEVER hold work: an unknown
   dependency is not evidence of a dependency, and a bug here freezes the
   whole board.
4. The grammar does not over-match prose that merely mentions the phrase.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from blocker_gate import BlockerGate, parse_blockers
from mockworld.fakes.fake_github import FakeGitHub
from tests.conftest import TaskFactory, TriageResultFactory
from tests.helpers import make_triage_phase, supply_once

_CHILD_BODY = "Parent: #11531\nBlocked by: #11533\n\n" + "A" * 100


def _phase_with_board(config, gh: FakeGitHub):
    phase, _state, triage, prs, store, _stop = make_triage_phase(config)
    prs.get_issue_state = gh.get_issue_state
    prs.get_issue_body = gh.get_issue_body
    triage.evaluate = AsyncMock(
        return_value=TriageResultFactory.create(issue_number=11534, ready=True)
    )
    store.get_triageable = supply_once(
        [TaskFactory.create(id=11534, title="Gateway P0 slice", body=_CHILD_BODY)]
    )
    return phase, triage, prs


async def test_open_blocker_holds_the_child_before_the_llm(config) -> None:
    gh = FakeGitHub()
    gh.add_issue(11533, "Fable P0", "the prerequisite")
    phase, triage, _prs = _phase_with_board(config, gh)

    await phase.triage_issues()

    triage.evaluate.assert_not_awaited()


async def test_held_child_is_not_parked(config) -> None:
    gh = FakeGitHub()
    gh.add_issue(11533, "Fable P0", "the prerequisite")
    phase, _triage, prs = _phase_with_board(config, gh)

    await phase.triage_issues()

    prs.swap_pipeline_labels.assert_not_called()


async def test_closed_blocker_releases_the_child(config) -> None:
    gh = FakeGitHub()
    gh.add_issue(11533, "Fable P0", "shipped", state="closed")
    phase, triage, _prs = _phase_with_board(config, gh)

    await phase.triage_issues()

    triage.evaluate.assert_awaited_once()


async def test_unreadable_blocker_fails_open() -> None:
    gh = FakeGitHub()
    gh.add_issue(2, "Prerequisite", "open")
    gh.set_rate_limit_mode(remaining=0)

    verdict = await BlockerGate().evaluate(gh, 1, "Blocked by: #2")

    assert verdict.blocked is False


def test_prose_mentioning_the_phrase_is_not_a_declaration() -> None:
    assert parse_blockers("The merge was blocked by a flaky test in #42.") == []
