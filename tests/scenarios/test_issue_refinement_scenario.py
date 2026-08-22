"""MockWorld scenario for IssueRefinementLoop's backlog dedup/priority pipeline
(#9957).

Drives the REAL `_do_work` end-to-end against a REAL `StateTracker` on
`tmp_path` and a `FakeGitHub` PR manager (`world.github`) — unlike the unit
coverage in `tests/test_issue_refinement_loop.py`, which exercises the same
paths against fakes built directly (not through `MockWorld`). This tier
proves the loop's real persistence layer (change-detection index, judged-pair
cache, open-proposal accumulation, digest issue) and FakeGitHub's issue/label/
comment trail agree with each other across a multi-tick round-trip — mirrors
`tests/scenarios/test_skill_prompt_refine_scenario.py`'s fixture style
(construct the loop directly, inject a scripted fake LLM via its
`refinement_llm` kwarg).

No network; the LLM is a scripted in-memory fake keyed on the fenced
`<issue_content number="N">` markers the engine's judgment/priority prompts
embed (same convention as the unit tests' `ScriptedRefinementLLM`, kept
self-contained here rather than imported — scenario tests don't reach into
unit-test modules in this repo).

Three scenarios (spec #9957 §3):

* `test_auto_close_path_closes_exactly_one_and_records_digest` — a seeded
  near-dup pair + a scripted exact_dup/high verdict naming a canonical closes
  EXACTLY the duplicate, with the evidence comment and `refinement-auto`
  label; the canonical stays open; the digest issue exists (labeled
  `hydraflow-refinement-digest`) with the close recorded; the pair is cached
  in state. The same tick also carries an unrelated, unlabeled, settled
  issue scripted P1 — proving the priority-relabel path applies a P-label via
  FakeGitHub in the same pass.
* `test_propose_path_no_close_and_proposal_persists_across_ticks` — a
  scripted likely_dup/medium verdict closes nothing; the digest carries the
  proposal and `refinement_open_proposals` state is populated. A second tick
  with one unrelated changed issue still renders the earlier proposal
  (persistence) without re-judging the cached pair.
* `test_cache_path_second_tick_unchanged_backlog_is_zero_llm` — after an
  auto-close settles the backlog, a second tick over the now-unchanged
  backlog makes zero LLM calls and leaves the digest body untouched (cache
  proof).
* `test_human_close_retires_digest_until_there_is_something_to_report` —
  (#11519) a human closes the digest; two refining-but-empty ticks leave the
  board unchanged; a tick with a proposal reopens exactly one digest; the
  human retires it again and a following empty tick does not reopen it.

The auto-close scenarios seed a LIVE digest (`_seed_live_digest`) because a
tick with only completed work never mints one (#11519): the digest is a
rolling report that is minted/reopened only for something a human needs to
see (an open operator question or an apply failure); a live one still
records every tick's closes and relabels.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from events import EventBus
from issue_refinement_loop import (
    _DIGEST_LABEL,
    _DIGEST_TITLE,
    _REFINEMENT_AUTO_LABEL,
    IssueRefinementLoop,
)
from state import StateTracker
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops

_ISSUE_RE = re.compile(r'<issue_content number="(\d+)">')

# Far enough in the past (relative to "now" at test time) to always clear the
# engine's 60-minute settling window (issue_refinement.SETTLING_WINDOW_MINUTES).
_SETTLED_UPDATED_AT = "2026-01-01T00:00:00Z"


def _dup_json(
    verdict: str, canonical: int, confidence: str, evidence: str = "x"
) -> str:
    return (
        f'{{"verdict": "{verdict}", "canonical": {canonical}, '
        f'"evidence": "{evidence}", "confidence": "{confidence}"}}'
    )


def _priority_json(priority: str, reason: str = "because") -> str:
    return f'{{"priority": "{priority}", "reason": "{reason}"}}'


class _ScriptedRefinementLLM:
    """Deterministic, network-free stand-in for the refinement LLM client.

    ``dup`` maps ``frozenset({a, b})`` -> raw verdict text; ``priority`` maps
    an issue number -> raw verdict text. Unscripted prompts fall back to a
    benign ``distinct`` / ``none`` verdict so an unrelated issue added mid-scenario
    never accidentally triggers a close or relabel. Every prompt is recorded
    in ``prompts`` so scenarios can assert on call counts (the cache proof).
    """

    def __init__(
        self,
        dup: dict[frozenset[int], str] | None = None,
        priority: dict[int, str] | None = None,
    ) -> None:
        self.dup = dup or {}
        self.priority = priority or {}
        self.prompts: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        nums = [int(n) for n in _ISSUE_RE.findall(prompt)]
        if "for duplicates" in prompt:
            return self.dup.get(
                frozenset(nums), _dup_json("distinct", min(nums), "high")
            )
        return self.priority.get(nums[0] if nums else 0, _priority_json("none"))

    def dup_calls(self) -> int:
        return sum(1 for p in self.prompts if "for duplicates" in p)


def _seed_near_dup_pair(world: MockWorld) -> None:
    """Two issues textually similar enough to clear the engine's prefilter
    score floor (title similarity + body token overlap) — same phrasing
    shape as the unit tests' `_near_dup_pair` fixture."""
    world.github.add_issue(
        101,
        "DiscoverRunner wedges the s51 sandbox subprocess group",
        "The DiscoverRunner leaves an orphaned child process that outlives the "
        "timeout so the s51 sandbox suite never reaps it and hangs forever.",
        labels=[],
    )
    world.github.add_issue(
        102,
        "DiscoverRunner wedges the s51 sandbox child process",
        "DiscoverRunner leaves an orphaned subprocess that outlives the timeout; "
        "the s51 sandbox suite never reaps the child process and hangs forever.",
        labels=[],
    )
    world.github.set_issue_updated_at(101, _SETTLED_UPDATED_AT)
    world.github.set_issue_updated_at(102, _SETTLED_UPDATED_AT)


def _seed_second_near_dup_pair(world: MockWorld) -> None:
    """A second pair (104/105) on an unrelated subject — a fresh operator
    question on a later tick (#11519 scenario)."""
    world.github.add_issue(
        104,
        "WikiCompileLoop double-writes the index on a cold restart",
        "After a cold restart the WikiCompileLoop writes the wiki index twice "
        "in the same tick, so the second write clobbers the first entry.",
        labels=[],
    )
    world.github.add_issue(
        105,
        "WikiCompileLoop double-writes the index after cold restart",
        "The WikiCompileLoop writes the wiki index twice in the same tick after "
        "a cold restart; the second write clobbers the first entry.",
        labels=[],
    )
    world.github.set_issue_updated_at(104, _SETTLED_UPDATED_AT)
    world.github.set_issue_updated_at(105, _SETTLED_UPDATED_AT)


# Mutually dissimilar title AND body: none clears the dup prefilter floor
# against any other seeded issue (identical bodies alone would — body overlap
# is 40% of the score; and a judged pair, even one judged distinct, renders as
# an operator question, which would give an "empty" tick something to say).
_UNRELATED = {
    200: ("Telemetry export gap on the metrics endpoint", "counters stop at noon"),
    201: ("OAuth login flow returns a blank page", "redirect lands on nothing"),
    202: ("Webhook retries hammer the staging deploy hook", "backoff never grows"),
}


def _seed_unrelated_issue(world: MockWorld, number: int) -> None:
    """A dissimilar settled issue: makes a tick non-quiet without any question."""
    title, body = _UNRELATED[number]
    world.github.add_issue(number, title, body)
    world.github.set_issue_updated_at(number, _SETTLED_UPDATED_AT)


_LIVE_DIGEST = 9000


def _seed_live_digest(world: MockWorld, state: StateTracker) -> int:
    """An OPEN rolling digest already on the board, pointed at by state — the
    steady state of a factory whose refinement loop had something to say on an
    earlier tick."""
    world.github.add_issue(
        _LIVE_DIGEST, _DIGEST_TITLE, "earlier digest body", labels=[_DIGEST_LABEL]
    )
    state.set_refinement_digest_issue(_LIVE_DIGEST)
    return _LIVE_DIGEST


def _digest_numbers(world: MockWorld) -> list[int]:
    return [
        n for n, issue in world.github._issues.items() if _DIGEST_LABEL in issue.labels
    ]


def _build_loop(
    world: MockWorld, tmp_path: Path, *, refinement_llm: _ScriptedRefinementLLM
) -> tuple[IssueRefinementLoop, StateTracker]:
    """An IssueRefinementLoop wired to `world.github` (FakeGitHub) with a REAL
    StateTracker/DedupStore on `tmp_path` — never MagicMock state, so
    assertions on the persisted index/judged-pair cache/open-proposals
    reflect the real persistence layer round-tripping through the loop's own
    code paths."""
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = StateTracker(state_file=tmp_path / "state.json")
    dedup = DedupStore("issue_refinement", tmp_path / "dedup.json")

    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )

    loop = IssueRefinementLoop(
        config=cfg,
        state=state,
        pr_manager=world.github,
        dedup=dedup,
        deps=deps,
        refinement_llm=refinement_llm,
    )
    return loop, state


async def test_auto_close_path_closes_exactly_one_and_records_digest(
    tmp_path: Path,
) -> None:
    """Seeded near-dup pair + scripted exact_dup/high verdict -> EXACTLY the
    duplicate closes, with the evidence comment + `refinement-auto` label; the
    canonical stays open; the LIVE digest records the close; the pair is
    cached. The same tick also proves the priority-relabel path: an unrelated,
    unlabeled, settled issue scripted P1 gets the P-label applied. The digest
    is seeded live because completed work alone never mints one (#11519)."""
    world = MockWorld(tmp_path)
    _seed_near_dup_pair(world)
    world.github.add_issue(
        103,
        "Loop watchdog silently drops the credit-exhausted signal",
        "The watchdog swallows CreditExhaustedError instead of reraising, so "
        "the loop keeps burning attempt budget against an exhausted account.",
        labels=[],
    )
    world.github.set_issue_updated_at(103, _SETTLED_UPDATED_AT)

    llm = _ScriptedRefinementLLM(
        dup={
            frozenset({101, 102}): _dup_json(
                "exact_dup", 101, "high", "same subprocess-group reap bug"
            )
        },
        priority={103: _priority_json("P1", "silently eats the credit signal")},
    )
    loop, state = _build_loop(world, tmp_path, refinement_llm=llm)
    live_digest = _seed_live_digest(world, state)

    stats = await loop._do_work()

    assert stats["closed"] == 1
    closed_numbers = sorted(
        n for n, i in world.github._issues.items() if i.state == "closed"
    )
    assert closed_numbers == [102]  # exactly one issue closed

    duplicate = world.github.issue(102)
    assert duplicate.state == "closed"
    # Closed as "not planned" (#10025): a deduped issue was retired, not
    # resolved — get_issue_state consumers must not read it as COMPLETED.
    assert await world.github.get_issue_state(102) == "NOT_PLANNED"
    assert _REFINEMENT_AUTO_LABEL in duplicate.labels
    assert any(
        c.body == "**Refinement (auto):** duplicate of #101 — "
        "same subprocess-group reap bug"
        for c in duplicate.comments
    )

    canonical = world.github.issue(101)
    assert canonical.state == "open"
    assert _REFINEMENT_AUTO_LABEL not in canonical.labels

    # The live digest records the close (and no second digest was minted).
    assert state.get_refinement_digest_issue() == live_digest
    digest = world.github.issue(live_digest)
    assert _DIGEST_LABEL in digest.labels
    assert "#102: duplicate of #101" in digest.body
    assert _digest_numbers(world) == [live_digest]

    # Pair is cached — keyed on the two issue numbers.
    judged = state.get_judged_pairs()
    assert len(judged) == 1
    assert judged[0].startswith("101:102:")

    # Priority relabel applied via FakeGitHub in the same tick.
    assert stats["relabeled"] == 1
    assert "P1" in world.github.issue(103).labels


async def test_propose_path_no_close_and_proposal_persists_across_ticks(
    tmp_path: Path,
) -> None:
    """A scripted likely_dup/medium verdict closes nothing; the digest carries
    the proposal and `refinement_open_proposals` state is populated. A second
    tick with one unrelated changed issue still renders the earlier proposal
    without re-judging the (now cached) pair."""
    world = MockWorld(tmp_path)
    _seed_near_dup_pair(world)
    llm = _ScriptedRefinementLLM(
        dup={
            frozenset({101, 102}): _dup_json(
                "likely_dup", 101, "medium", "similar title, unconfirmed scope overlap"
            )
        }
    )
    loop, state = _build_loop(world, tmp_path, refinement_llm=llm)
    # Incremental mode from the first tick on — change-detection alone (new
    # issues count as changed) is enough to drive judgment.
    state.set_refinement_last_full_sweep(datetime.now(UTC))

    stats = await loop._do_work()

    assert stats["closed"] == 0
    assert world.github.issue(101).state == "open"
    assert world.github.issue(102).state == "open"

    digest_num = state.get_refinement_digest_issue()
    assert digest_num > 0
    digest_body = world.github.issue(digest_num).body
    assert "#101 vs #102" in digest_body
    assert "likely_dup" in digest_body

    open_proposals = state.get_refinement_open_proposals()
    assert len(open_proposals) == 1
    assert open_proposals[0]["kind"] == "dup"
    assert {open_proposals[0]["a"], open_proposals[0]["b"]} == {101, 102}

    dup_calls_after_first_tick = llm.dup_calls()
    assert dup_calls_after_first_tick == 1

    # Second tick: an unrelated new issue makes the tick non-quiet, but 101/102
    # are unchanged (their pair stays cached, not re-judged).
    world.github.add_issue(
        200, "Telemetry export gap on the metrics endpoint", "unrelated body", labels=[]
    )
    world.github.set_issue_updated_at(200, _SETTLED_UPDATED_AT)

    stats2 = await loop._do_work()

    assert stats2["changed"] >= 1
    assert llm.dup_calls() == dup_calls_after_first_tick  # pair not re-judged
    # The earlier open proposal still renders — not just this tick's questions.
    assert "#101 vs #102" in world.github.issue(digest_num).body


async def test_cache_path_second_tick_unchanged_backlog_is_zero_llm(
    tmp_path: Path,
) -> None:
    """After an auto-close settles the backlog, a second tick over the
    now-unchanged backlog makes zero LLM calls and leaves the digest body
    untouched — the cache proof."""
    world = MockWorld(tmp_path)
    _seed_near_dup_pair(world)
    llm = _ScriptedRefinementLLM(
        dup={
            frozenset({101, 102}): _dup_json(
                "exact_dup", 101, "high", "same subprocess-group reap bug"
            )
        }
    )
    loop, state = _build_loop(world, tmp_path, refinement_llm=llm)
    state.set_refinement_last_full_sweep(datetime.now(UTC))  # incremental mode
    digest_num = _seed_live_digest(world, state)  # completed work never mints one

    stats1 = await loop._do_work()
    assert stats1["closed"] == 1  # #102 auto-closed, drops out of the backlog

    assert state.get_refinement_digest_issue() == digest_num
    digest_body_after_first_tick = world.github.issue(digest_num).body
    assert "#102: duplicate of #101" in digest_body_after_first_tick
    calls_after_first_tick = len(llm.prompts)
    assert calls_after_first_tick > 0

    stats2 = await loop._do_work()

    assert stats2["changed"] == 0
    assert len(llm.prompts) == calls_after_first_tick  # zero new LLM calls
    assert world.github.issue(digest_num).body == digest_body_after_first_tick


async def test_human_close_retires_digest_until_there_is_something_to_report(
    tmp_path: Path,
) -> None:
    """#11519 — the #10224 timeline, over MockWorld's FakeGitHub + real state:
    a proposal mints the digest; a human closes it (and answers the question);
    two refining-but-empty ticks leave the board unchanged (no reopen, no
    fresh digest, body untouched); a tick with a new proposal reopens exactly
    one digest (the same rolling issue); the human retires it again and a
    following empty tick does not reopen it."""
    world = MockWorld(tmp_path)
    _seed_near_dup_pair(world)
    llm = _ScriptedRefinementLLM(
        dup={
            frozenset({101, 102}): _dup_json("likely_dup", 101, "medium"),
            frozenset({104, 105}): _dup_json("likely_dup", 104, "medium"),
        }
    )
    loop, state = _build_loop(world, tmp_path, refinement_llm=llm)
    state.set_refinement_last_full_sweep(datetime.now(UTC))  # incremental mode

    # Tick 1: the 101/102 question mints the digest.
    await loop._do_work()
    digest = state.get_refinement_digest_issue()
    assert digest > 0
    assert _digest_numbers(world) == [digest]

    # A human retires the rolling report and answers the open question.
    await world.github.close_issue(digest)
    await world.github.close_issue(102, reason="not planned")
    retired_body = world.github.issue(digest).body

    # Ticks 2-3: refining, but nothing to report -> board unchanged.
    for number in (200, 201):
        _seed_unrelated_issue(world, number)
        before = len(world.github._issues)
        stats = await loop._do_work()
        assert stats["changed"] >= 1
        assert stats["proposals"] == 0
        assert stats["open_questions"] == 0
        assert world.github.issue(digest).state == "closed"
        assert world.github.issue(digest).body == retired_body
        assert len(world.github._issues) == before
    assert _digest_numbers(world) == [digest]

    # Tick 4: a new proposal reopens the SAME digest, exactly once.
    _seed_second_near_dup_pair(world)
    before = len(world.github._issues)
    stats = await loop._do_work()
    assert stats["proposals"] == 1
    assert world.github.issue(digest).state == "open"
    assert "#104 vs #105" in world.github.issue(digest).body
    assert len(world.github._issues) == before
    assert _digest_numbers(world) == [digest]

    # Retired again + answered; tick 5 has nothing to say -> stays closed.
    await world.github.close_issue(digest)
    await world.github.close_issue(105, reason="not planned")
    retired_body = world.github.issue(digest).body
    _seed_unrelated_issue(world, 202)
    before = len(world.github._issues)
    stats = await loop._do_work()
    assert stats["open_questions"] == 0
    assert world.github.issue(digest).state == "closed"
    assert world.github.issue(digest).body == retired_body
    assert len(world.github._issues) == before
    assert _digest_numbers(world) == [digest]
