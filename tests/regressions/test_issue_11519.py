"""Regression #11519: IssueRefinementLoop reopens the human-retired digest
(#10224) on ticks with nothing to report.

Timeline that motivated this (rolling digest #10224): the operator closed the
digest on 2026-08-17 with the ruling "a human close retires the digest — it is
a rolling report, not a work item", and the next day's tick reopened it while
its own body still read "Proposed closes: none this tick / proposals: 0".

``IssueRefinementLoop._write_digest`` (src/issue_refinement_loop.py) treats ANY
closed stored digest as something to recover — reopen it (``PRPort`` grew a
``reopen_issue`` seam, so ``_reopen_digest``'s capability probe now succeeds;
its docstring still claims the port has no reopen method) or mint a fresh one —
with no check that the tick has anything to say and no distinction between "a
stale GC pass closed it" and "a human retired it".

Pins (unit, fakes-only per the loop suite's idiom):

* stored digest CLOSED + a non-quiet tick with ``proposals == 0`` and
  ``open_questions == 0`` → no reopen, no re-mint, body untouched — RED before
  the fix, which reopens the retired digest and rewrites its body;
* stored digest CLOSED + a tick with ≥1 proposal → exactly one
  reopen-or-create with the body written (scope guard for the eventual fix: a
  real operator question must still resurface — green today, must stay green).
"""

from __future__ import annotations

from datetime import UTC, datetime

from tests.test_issue_refinement_loop import (
    ScriptedRefinementLLM,
    _cfg,
    _dup_json,
    _env,
    _make_loop,
    _near_dup_pair,
)


async def test_empty_tick_does_not_reopen_human_retired_digest(tmp_path) -> None:
    """A human close retires the digest: a tick with zero proposals and zero
    open questions must not reopen it, re-mint one, or rewrite its body."""
    gh, state, dedup, bus = _env(tmp_path)
    # One unlabeled backlog issue: no dup pair is possible, and the scripted
    # LLM scores it "none" — its current label — so a non-quiet tick still has
    # nothing to propose and nothing to ask (the #10224 "none this tick" shape).
    gh.add_issue(
        101, "Docs: clarify digest retirement policy", "initial body", labels=[]
    )
    state.set_refinement_last_full_sweep(datetime.now(UTC))  # incremental mode
    llm = ScriptedRefinementLLM()
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)

    await loop._do_work()  # tick N: mints the rolling digest
    digest_num = state.get_refinement_digest_issue()
    assert digest_num > 0
    retired_body = gh._issues[digest_num].body
    board_size_after_tick_n = len(gh._issues)

    # The human retires the digest (#10224, 2026-08-17 ruling).
    gh._issues[digest_num].state = "closed"

    # Tick N+1: non-quiet (the issue was edited, so change-detection re-marks
    # it and the tick runs its full pipeline) but still empty-handed — one
    # issue ⇒ no pairs; "none" == current label ⇒ no question, no relabel.
    gh._issues[101].body = "Edited body so change-detection re-marks #101."
    gh.set_issue_updated_at(101, "2026-08-18T00:00:00Z")
    stats = await loop._do_work()

    # Regime pins: this tick reached the digest write with an empty hand.
    assert stats["status"] == "ok"
    assert stats["proposals"] == 0
    assert stats["open_questions"] == 0
    assert stats["closed"] == 0
    assert stats["relabeled"] == 0

    # The retirement stands: no reopen, no re-mint, no body rewrite.
    assert gh._issues[digest_num].state == "closed"
    assert gh._issues[digest_num].body == retired_body
    assert state.get_refinement_digest_issue() == digest_num
    assert len(gh._issues) == board_size_after_tick_n


async def test_proposal_tick_still_reopens_the_rolling_digest(tmp_path) -> None:
    """Scope guard: a tick that DOES have an operator question must still
    resurface the closed digest — one reopen-or-create, body written."""
    gh, state, dedup, bus = _env(tmp_path)
    _near_dup_pair(gh)
    state.set_refinement_last_full_sweep(datetime.now(UTC))  # incremental mode
    llm = ScriptedRefinementLLM(
        dup={frozenset({101, 102}): _dup_json("likely_dup", 101, "medium")}
    )
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)

    await loop._do_work()  # tick N: one dup proposal, digest minted
    digest_num = state.get_refinement_digest_issue()
    assert digest_num > 0
    gh._issues[digest_num].state = "closed"  # closed out-of-band

    # Tick N+1: a body edit invalidates the pair's cache key so it re-judges —
    # the tick again carries a proposal, so the digest must resurface.
    gh._issues[101].body = "Rewritten body forces the pair to re-judge."
    gh.set_issue_updated_at(101, "2026-08-18T00:00:00Z")
    stats = await loop._do_work()

    assert stats["proposals"] == 1
    assert state.get_refinement_digest_issue() == digest_num  # reused, not churned
    assert gh._issues[digest_num].state == "open"
    assert "#101 vs #102" in gh._issues[digest_num].body
