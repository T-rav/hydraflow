"""Tests for IssueRefinementLoop (spec #9957) — fakes only, no network.

Mirrors the SkillPromptEvalLoop fixture idiom but drives a real
``FakeGitHub`` + ``StateTracker`` so auto-close / relabel / digest behaviour is
asserted against fake *state*, not mock call-counts. The LLM is a scripted
in-memory fake keyed on the fenced ``<issue_content number="N">`` markers the
engine's judgment/priority prompts embed.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from events import EventBus, EventType
from issue_refinement_loop import (
    _DIGEST_DEDUP_KEY,
    _DIGEST_LABEL,
    _DIGEST_TITLE,
    _REFINEMENT_AUTO_LABEL,
    IssueRefinementLoop,
)
from mockworld.fakes.fake_github import FakeGitHub
from state import StateTracker
from subprocess_util import CreditExhaustedError

# --- scripted LLM fake --------------------------------------------------------

_ISSUE_RE = re.compile(r'<issue_content number="(\d+)">')


def _dup_json(
    verdict: str, canonical: int, confidence: str, evidence: str = "x"
) -> str:
    return (
        f'{{"verdict": "{verdict}", "canonical": {canonical}, '
        f'"evidence": "{evidence}", "confidence": "{confidence}"}}'
    )


def _priority_json(priority: str, reason: str = "because") -> str:
    return f'{{"priority": "{priority}", "reason": "{reason}"}}'


class ScriptedRefinementLLM:
    """In-memory ``refinement_llm`` fake.

    ``dup`` maps ``frozenset({a, b})`` → raw verdict text; ``priority`` maps an
    issue number → raw verdict text. Unscripted prompts fall back to a benign
    ``distinct`` / ``none`` verdict. Every prompt is recorded in ``prompts``.
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

    def priority_nums(self) -> set[int]:
        out: set[int] = set()
        for p in self.prompts:
            if "for priority" not in p:
                continue
            m = _ISSUE_RE.search(p)
            if m:
                out.add(int(m.group(1)))
        return out


# --- fixtures / helpers -------------------------------------------------------


def _cfg(tmp_path, **overrides) -> HydraFlowConfig:
    return HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow", **overrides)


def _make_loop(cfg, gh, state, dedup, bus, llm=None, *, enabled=True):
    deps = LoopDeps(
        event_bus=bus,
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )
    return IssueRefinementLoop(
        config=cfg,
        state=state,
        pr_manager=gh,
        dedup=dedup,
        deps=deps,
        refinement_llm=llm,
    )


def _env(tmp_path):
    gh = FakeGitHub()
    state = StateTracker(state_file=tmp_path / "state.json")
    dedup = DedupStore("issue_refinement", tmp_path / "dedup.json")
    bus = EventBus()
    return gh, state, dedup, bus


def _near_dup_pair(gh: FakeGitHub) -> None:
    gh.add_issue(
        101,
        "DiscoverRunner wedges the s51 sandbox subprocess group",
        "The DiscoverRunner leaves an orphaned child process that outlives the "
        "timeout so the s51 sandbox suite never reaps it and hangs forever.",
        labels=[],
    )
    gh.add_issue(
        102,
        "DiscoverRunner wedges the s51 sandbox child process",
        "DiscoverRunner leaves an orphaned subprocess that outlives the timeout; "
        "the s51 sandbox suite never reaps the child process and hangs forever.",
        labels=[],
    )


def _refinement_events(bus: EventBus):
    return [e for e in bus.get_history() if e.type == EventType.ISSUE_REFINEMENT_UPDATE]


# --- tests --------------------------------------------------------------------


async def test_kill_switch_config_disabled_is_noop(tmp_path) -> None:
    gh, state, dedup, bus = _env(tmp_path)
    _near_dup_pair(gh)
    llm = ScriptedRefinementLLM()
    loop = _make_loop(
        _cfg(tmp_path, issue_refinement_enabled=False), gh, state, dedup, bus, llm
    )

    stats = await loop._do_work()

    assert stats == {"status": "config_disabled"}
    assert llm.prompts == []
    assert gh._issues[102].state == "open"
    assert _refinement_events(bus) == []


async def test_kill_switch_enabled_cb_disabled_is_noop(tmp_path) -> None:
    gh, state, dedup, bus = _env(tmp_path)
    _near_dup_pair(gh)
    llm = ScriptedRefinementLLM()
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm, enabled=False)

    stats = await loop._do_work()

    assert stats == {"status": "disabled"}
    assert llm.prompts == []


async def test_unchanged_backlog_short_circuits_without_llm(tmp_path) -> None:
    gh, state, dedup, bus = _env(tmp_path)
    _near_dup_pair(gh)
    # Pre-seed the index to match the backlog and mark a full sweep as just done.
    raw = await gh.list_open_issues()
    issues = [IssueRefinementLoop._to_refinement_issue(r) for r in raw]
    state.set_refinement_index(
        {str(i.number): IssueRefinementLoop._index_entry(i) for i in issues}
    )
    state.set_refinement_last_full_sweep(datetime.now(UTC))

    llm = ScriptedRefinementLLM()
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)
    stats = await loop._do_work()

    assert stats["status"] == "ok"
    assert stats["changed"] == 0
    assert llm.prompts == []  # zero LLM calls on a no-change tick
    assert _refinement_events(bus) == []  # heartbeat only


async def test_empty_backlog_is_cheap_noop(tmp_path) -> None:
    gh, state, dedup, bus = _env(tmp_path)
    llm = ScriptedRefinementLLM()
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)

    stats = await loop._do_work()

    assert stats["status"] == "ok"
    assert stats["backlog"] == 0
    assert llm.prompts == []
    assert state.get_refinement_digest_issue() == 0  # no digest created


async def test_weekly_full_sweep_triggers_and_advances_marker(tmp_path) -> None:
    gh, state, dedup, bus = _env(tmp_path)
    _near_dup_pair(gh)
    # Index already matches (an incremental tick would find nothing)...
    raw = await gh.list_open_issues()
    issues = [IssueRefinementLoop._to_refinement_issue(r) for r in raw]
    state.set_refinement_index(
        {str(i.number): IssueRefinementLoop._index_entry(i) for i in issues}
    )
    # ...but the last full sweep is 8 days ago, so a sweep is due.
    eight_days_ago = datetime.now(UTC) - timedelta(days=8)
    state.set_refinement_last_full_sweep(eight_days_ago)

    llm = ScriptedRefinementLLM()
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)
    stats = await loop._do_work()

    assert stats["full_sweep"] is True
    assert llm.prompts, "full sweep must judge/score even with a matching index"
    assert state.get_refinement_last_full_sweep() > eight_days_ago


async def test_pair_budget_caps_dup_judgments(tmp_path) -> None:
    gh, state, dedup, bus = _env(tmp_path)
    for n in (201, 202, 203):
        gh.add_issue(
            n,
            "DiscoverRunner wedges the s51 sandbox subprocess group",
            "DiscoverRunner leaves an orphaned child that outlives the timeout; "
            "s51 never reaps it and the sandbox suite hangs forever.",
            labels=[],
        )
    # 3 mutually-similar issues → C(3,2)=3 candidate pairs; budget caps to 1.
    llm = ScriptedRefinementLLM()
    loop = _make_loop(
        _cfg(tmp_path, issue_refinement_pair_budget=1), gh, state, dedup, bus, llm
    )
    await loop._do_work()

    assert llm.dup_calls() == 1


async def test_unparseable_verdict_goes_to_digest_and_is_cached(tmp_path) -> None:
    gh, state, dedup, bus = _env(tmp_path)
    _near_dup_pair(gh)
    llm = ScriptedRefinementLLM(dup={frozenset({101, 102}): "this is not json at all"})
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)

    await loop._do_work()

    # Pair cached despite the parse failure (no re-spend next tick).
    judged = state.get_judged_pairs()
    assert len(judged) == 1
    assert judged[0].startswith("101:102:")
    # Surfaced as an operator question in the digest, not auto-closed.
    assert gh._issues[102].state == "open"
    digest = gh._issues[state.get_refinement_digest_issue()]
    assert "#101 vs #102" in digest.body
    assert "(low)" in digest.body


async def test_auto_close_applies_comment_label_and_close(tmp_path) -> None:
    gh, state, dedup, bus = _env(tmp_path)
    _near_dup_pair(gh)
    llm = ScriptedRefinementLLM(
        dup={frozenset({101, 102}): _dup_json("exact_dup", 101, "high", "same reap")}
    )
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)

    stats = await loop._do_work()

    assert stats["closed"] == 1
    dup = gh._issues[102]
    assert dup.state == "closed"
    assert _REFINEMENT_AUTO_LABEL in dup.labels
    assert any(
        c.body.startswith("**Refinement (auto):** duplicate of #101 — ")
        for c in dup.comments
    )
    # Canonical is untouched.
    assert gh._issues[101].state == "open"
    assert _REFINEMENT_AUTO_LABEL not in gh._issues[101].labels


async def test_relabel_adds_new_and_removes_previous(tmp_path) -> None:
    gh, state, dedup, bus = _env(tmp_path)
    gh.add_issue(301, "Investigate the wedged planner phase", "body", labels=["P2"])
    llm = ScriptedRefinementLLM(
        priority={301: _priority_json("P0", "blocks the factory")}
    )
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)

    stats = await loop._do_work()

    assert stats["relabeled"] == 1
    labels = gh._issues[301].labels
    assert "P0" in labels
    assert "P2" not in labels


async def test_per_action_failure_isolated_and_digested(tmp_path) -> None:
    gh, state, dedup, bus = _env(tmp_path)
    _near_dup_pair(gh)
    gh.close_issue = AsyncMock(side_effect=RuntimeError("boom"))  # raising close
    llm = ScriptedRefinementLLM(
        dup={frozenset({101, 102}): _dup_json("exact_dup", 101, "high")}
    )
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)

    stats = await loop._do_work()

    # Tick completes cleanly; the failing close is recorded, not fatal.
    assert stats["status"] == "ok"
    assert stats["closed"] == 0
    assert stats["apply_failures"] == 1
    digest = gh._issues[state.get_refinement_digest_issue()]
    assert "Apply failures" in digest.body
    assert "close #102" in digest.body


async def test_credit_error_during_apply_reraises(tmp_path) -> None:
    gh, state, dedup, bus = _env(tmp_path)
    _near_dup_pair(gh)
    gh.close_issue = AsyncMock(side_effect=CreditExhaustedError("out of credit"))
    llm = ScriptedRefinementLLM(
        dup={frozenset({101, 102}): _dup_json("exact_dup", 101, "high")}
    )
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)

    with pytest.raises(CreditExhaustedError):
        await loop._do_work()


async def test_digest_created_then_updated(tmp_path) -> None:
    gh, state, dedup, bus = _env(tmp_path)
    _near_dup_pair(gh)
    llm = ScriptedRefinementLLM()
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)

    await loop._do_work()
    digest_num = state.get_refinement_digest_issue()
    assert digest_num > 0
    digest = gh._issues[digest_num]
    assert digest.title == _DIGEST_TITLE
    assert _DIGEST_LABEL in digest.labels
    assert _DIGEST_DEDUP_KEY_present(dedup)
    issue_count_after_first = len(gh._issues)

    # Second tick: change an issue so the tick refines and rewrites the digest.
    gh._issues[101].body = "Completely different body text now, reindex me please."
    gh.set_issue_updated_at(101, "2026-07-19T00:00:00Z")
    await loop._do_work()

    assert state.get_refinement_digest_issue() == digest_num  # same rolling issue
    assert len(gh._issues) == issue_count_after_first  # updated, not re-created


def _DIGEST_DEDUP_KEY_present(dedup: DedupStore) -> bool:
    from issue_refinement_loop import _DIGEST_DEDUP_KEY

    return _DIGEST_DEDUP_KEY in dedup.get()


async def test_publishes_one_refinement_event_with_counters(tmp_path) -> None:
    gh, state, dedup, bus = _env(tmp_path)
    _near_dup_pair(gh)
    llm = ScriptedRefinementLLM(
        dup={frozenset({101, 102}): _dup_json("exact_dup", 101, "high")}
    )
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)

    await loop._do_work()

    events = _refinement_events(bus)
    assert len(events) == 1
    data = events[0].data
    assert data["closed"] == 1
    assert {"closed", "relabeled", "proposals", "judged", "cache_hits"} <= set(data)


async def test_incremental_priority_skips_already_p_labeled(tmp_path) -> None:
    gh, state, dedup, bus = _env(tmp_path)
    gh.add_issue(401, "OAuth login flow returns a blank page", "b1", labels=["P1"])
    gh.add_issue(402, "Metrics dashboard chart renders upside down", "b2", labels=[])
    # Incremental tick: sweep just done, both issues are new → both "changed".
    state.set_refinement_last_full_sweep(datetime.now(UTC))
    llm = ScriptedRefinementLLM()
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)

    stats = await loop._do_work()

    assert stats["full_sweep"] is False
    # 401 already carries a P-label → skipped; 402 (no P-label) → scored.
    assert llm.priority_nums() == {402}


async def test_full_sweep_scores_even_p_labeled(tmp_path) -> None:
    gh, state, dedup, bus = _env(tmp_path)
    gh.add_issue(401, "OAuth login flow returns a blank page", "b1", labels=["P1"])
    gh.add_issue(402, "Metrics dashboard chart renders upside down", "b2", labels=[])
    # Full sweep due → every unguarded issue is scored, P-labeled or not.
    state.set_refinement_last_full_sweep(datetime.now(UTC) - timedelta(days=8))
    llm = ScriptedRefinementLLM()
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)

    stats = await loop._do_work()

    assert stats["full_sweep"] is True
    assert llm.priority_nums() == {401, 402}


# --- review fixes: stale-close guard, digest self-participation, proposal ----
# --- persistence, close-gated labeling, digest recovery (#9957) --------------


async def test_stale_close_skips_and_leaves_pair_rejudgeable(tmp_path) -> None:
    """A canonical/duplicate closed between judgment and apply must abort the
    close, surface a stale-judgment failure, and NOT cache the pair."""
    gh, state, dedup, bus = _env(tmp_path)
    _near_dup_pair(gh)  # 101, 102 both open at fetch

    async def _state(number: int) -> str:
        # #101 was closed out-of-band mid-tick; #102 is still open.
        return "COMPLETED" if number == 101 else "OPEN"

    gh.get_issue_state = _state
    llm = ScriptedRefinementLLM(
        dup={frozenset({101, 102}): _dup_json("exact_dup", 101, "high")}
    )
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)

    stats = await loop._do_work()

    assert stats["status"] == "ok"
    assert stats["closed"] == 0
    assert stats["apply_failures"] == 1
    # Duplicate untouched — no close, no fitness label.
    assert gh._issues[102].state == "open"
    assert _REFINEMENT_AUTO_LABEL not in gh._issues[102].labels
    # Not cached: the pair re-judges next tick against fresh content.
    assert state.get_judged_pairs() == []
    digest = gh._issues[state.get_refinement_digest_issue()]
    assert "stale judgment" in digest.body


async def test_failing_close_adds_no_label_and_leaves_pair_rejudgeable(
    tmp_path,
) -> None:
    """A soft close failure (returns False) must gate the label off and leave
    the pair un-cached so it re-judges next tick."""
    gh, state, dedup, bus = _env(tmp_path)
    _near_dup_pair(gh)
    gh.close_issue = AsyncMock(return_value=False)
    llm = ScriptedRefinementLLM(
        dup={frozenset({101, 102}): _dup_json("exact_dup", 101, "high")}
    )
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)

    stats = await loop._do_work()

    assert stats["closed"] == 0
    assert stats["apply_failures"] == 1
    dup = gh._issues[102]
    assert dup.state == "open"
    assert _REFINEMENT_AUTO_LABEL not in dup.labels  # label gated on a real close
    assert state.get_judged_pairs() == []  # re-judgeable


async def test_quiet_tick_after_refinement_is_zero_llm_and_digest_untouched(
    tmp_path,
) -> None:
    """The rolling digest issue must not count as its own change signal: a quiet
    tick after a refinement takes the genuine zero-LLM short-circuit and does not
    rewrite the digest."""
    gh, state, dedup, bus = _env(tmp_path)
    _near_dup_pair(gh)
    state.set_refinement_last_full_sweep(datetime.now(UTC))  # incremental mode
    llm = ScriptedRefinementLLM()
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)

    # Tick N: refines the two new issues, creates the digest.
    await loop._do_work()
    digest_num = state.get_refinement_digest_issue()
    assert digest_num > 0
    calls_after_n = len(llm.prompts)
    assert calls_after_n > 0
    digest_body_after_n = gh._issues[digest_num].body

    # Tick N+1: nothing else changed; the now-open digest issue must be ignored.
    stats = await loop._do_work()

    assert stats["changed"] == 0
    assert len(llm.prompts) == calls_after_n  # zero new LLM calls
    assert gh._issues[digest_num].body == digest_body_after_n  # untouched


async def test_earlier_open_proposal_re_renders_on_later_changed_tick(
    tmp_path,
) -> None:
    """An operator question raised on an earlier tick keeps rendering on a later
    tick that refines unrelated changes (the pair itself is cached, not
    re-judged)."""
    gh, state, dedup, bus = _env(tmp_path)
    _near_dup_pair(gh)
    state.set_refinement_last_full_sweep(datetime.now(UTC))
    llm = ScriptedRefinementLLM(
        dup={frozenset({101, 102}): _dup_json("likely_dup", 101, "medium")}
    )
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)

    await loop._do_work()  # tick N: likely_dup -> operator question persisted
    digest_num = state.get_refinement_digest_issue()
    assert "#101 vs #102" in gh._issues[digest_num].body

    # Tick N+1: an unrelated new issue makes the tick non-quiet; 101/102 unchanged.
    gh.add_issue(
        200, "Telemetry export gap on the metrics endpoint", "unrelated", labels=[]
    )
    stats = await loop._do_work()

    assert stats["changed"] >= 1
    # The earlier open proposal is still rendered — not just this tick's.
    assert "#101 vs #102" in gh._issues[digest_num].body


async def test_digest_recreated_when_stored_issue_closed(tmp_path) -> None:
    """A closed digest issue is not silently written — a fresh one is minted."""
    gh, state, dedup, bus = _env(tmp_path)
    _near_dup_pair(gh)
    state.set_refinement_last_full_sweep(datetime.now(UTC))
    llm = ScriptedRefinementLLM()
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)

    await loop._do_work()  # tick N: create digest
    old_digest = state.get_refinement_digest_issue()
    assert old_digest > 0
    gh._issues[old_digest].state = "closed"  # closed out-of-band

    # Tick N+1: change an issue so the tick refines and writes the digest.
    gh._issues[101].body = "Rewritten body to force a change and re-refinement."
    gh.set_issue_updated_at(101, "2026-07-19T00:00:00Z")
    await loop._do_work()

    new_digest = state.get_refinement_digest_issue()
    assert new_digest != old_digest
    assert gh._issues[new_digest].state == "open"
    assert _DIGEST_LABEL in gh._issues[new_digest].labels


async def test_digest_adopted_by_label_when_state_lost_number(tmp_path) -> None:
    """State number reset to 0 while the create-once dedup key survives: adopt
    the open digest found by label instead of minting a duplicate."""
    gh, state, dedup, bus = _env(tmp_path)
    _near_dup_pair(gh)
    state.set_refinement_last_full_sweep(datetime.now(UTC))
    # A real digest exists (open, labeled) but state lost its number...
    gh.add_issue(9001, _DIGEST_TITLE, "stale digest body", labels=[_DIGEST_LABEL])
    # ...while the create-once dedup key survived.
    d = dedup.get()
    d.add(_DIGEST_DEDUP_KEY)
    dedup.set_all(d)
    assert state.get_refinement_digest_issue() == 0

    llm = ScriptedRefinementLLM()
    loop = _make_loop(_cfg(tmp_path), gh, state, dedup, bus, llm)
    issue_count_before = len(gh._issues)

    await loop._do_work()

    assert state.get_refinement_digest_issue() == 9001  # adopted, not re-created
    assert len(gh._issues) == issue_count_before  # no duplicate digest
    assert gh._issues[9001].body != "stale digest body"  # body refreshed
