"""Regression pin for #11519 — a human close retires the refinement digest.

The bug: ``IssueRefinementLoop._write_digest`` treated a CLOSED stored digest
as something to recover on EVERY refining tick, so after a human closed the
rolling digest (#10224: closed by T-rav 2026-08-02 and 2026-08-17) the bot
reopened it (2026-08-14 and 2026-08-18) with a body still reading
"Proposed closes: none this tick / proposals: 0". Nothing checked whether the
tick had anything to say.

The operator's 2026-08-17 ruling is the spec: the digest is a rolling report,
not a work item; a human close retires it; the loop re-files only when it has
something to report. This pin replays the #10224 timeline against the real
loop over ``FakeGitHub`` + a real ``StateTracker``:

1. a proposal mints the digest; a human retires it (and answers the question);
2. two refining-but-empty ticks leave the board unchanged — no reopen, no
   fresh digest, body untouched;
3. a tick with a new proposal reopens the SAME digest exactly once;
4. the human retires it again (and answers); a further empty tick does not
   reopen it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from issue_refinement_loop import _DIGEST_LABEL
from tests.test_issue_refinement_loop import (
    ScriptedRefinementLLM,
    _add_unrelated,
    _cfg,
    _dup_json,
    _env,
    _make_loop,
    _near_dup_pair,
    _second_near_dup_pair,
)


def _digest_issue_numbers(gh) -> list[int]:
    return [n for n, i in gh._issues.items() if _DIGEST_LABEL in i.labels]


async def test_human_close_retires_digest_until_there_is_something_to_report(
    tmp_path,
) -> None:
    gh, state, dedup, bus = _env(tmp_path)
    _near_dup_pair(gh)
    state.set_refinement_last_full_sweep(datetime.now(UTC))  # incremental mode
    llm = ScriptedRefinementLLM(
        dup={
            frozenset({101, 102}): _dup_json("likely_dup", 101, "medium"),
            frozenset({104, 105}): _dup_json("likely_dup", 104, "medium"),
        }
    )
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)

    # 1. A proposal mints the digest; a human retires it and answers the question.
    await loop._do_work()
    digest = state.get_refinement_digest_issue()
    assert digest > 0
    await gh.close_issue(digest)
    await gh.close_issue(102, reason="not planned")
    retired_body = gh._issues[digest].body

    # 2. Two refining ticks with nothing to report: board unchanged.
    for number in (200, 201):
        _add_unrelated(gh, number)
        before = len(gh._issues)
        stats = await loop._do_work()
        assert stats["changed"] >= 1
        assert stats["proposals"] == 0
        assert stats["open_questions"] == 0
        assert gh._issues[digest].state == "closed"
        assert gh._issues[digest].body == retired_body
        assert len(gh._issues) == before
    assert _digest_issue_numbers(gh) == [digest]

    # 3. A tick with a proposal reopens the same digest exactly once.
    _second_near_dup_pair(gh)
    before = len(gh._issues)
    stats = await loop._do_work()
    assert stats["proposals"] == 1
    assert gh._issues[digest].state == "open"
    assert "#104 vs #105" in gh._issues[digest].body
    assert len(gh._issues) == before
    assert _digest_issue_numbers(gh) == [digest]

    # 4. Retired again + question answered; a further empty tick leaves it closed.
    await gh.close_issue(digest)
    await gh.close_issue(105, reason="not planned")
    retired_body = gh._issues[digest].body
    _add_unrelated(gh, 202)
    before = len(gh._issues)
    stats = await loop._do_work()
    assert stats["open_questions"] == 0
    assert gh._issues[digest].state == "closed"
    assert gh._issues[digest].body == retired_body
    assert len(gh._issues) == before
    assert _digest_issue_numbers(gh) == [digest]
