"""Unit tests for LiveCorpusReplayLoop (Phase 2 of #8786).

Covers the loop's reaction surface (Pattern B per
``docs/standards/testing/README.md`` §How to write each layer):

- Empty corpus → status=ok, compared=0.
- Sample with no registered dispatcher → skipped, no issue filed.
- Sample matched by dispatcher with no drift → compared=1, no issue.
- Sample matched by dispatcher WITH drift → issue filed (hydraflow-find).
- Dedup: identical drift on consecutive ticks files at most one issue.
- Dispatcher raising is caught — loop continues, errors counted.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from contracts.shadow import ShadowCorpus
from dedup_store import DedupStore
from events import EventBus
from live_corpus_replay_loop import LiveCorpusReplayLoop


class _FakeState:
    """Minimal StateTracker stub for the per-signature attempt counters plus
    the fleet-wide shadow-drift rollup / escalation issue slots."""

    def __init__(self) -> None:
        self._attempts: dict[str, int] = {}
        self._rollup: dict | None = None
        self._escalation: int | None = None

    def get_live_corpus_drift_attempts(self, sig: str) -> int:
        return self._attempts.get(sig, 0)

    def inc_live_corpus_drift_attempts(self, sig: str) -> int:
        self._attempts[sig] = self._attempts.get(sig, 0) + 1
        return self._attempts[sig]

    def clear_live_corpus_drift_attempts(self) -> None:
        self._attempts.clear()

    def get_live_corpus_drift_rollup(self) -> dict | None:
        return dict(self._rollup) if self._rollup else None

    def set_live_corpus_drift_rollup(
        self, *, issue_number: int, signature_hash: str
    ) -> None:
        self._rollup = {"issue_number": issue_number, "signature_hash": signature_hash}

    def clear_live_corpus_drift_rollup(self) -> None:
        self._rollup = None

    def get_live_corpus_escalation_issue(self) -> int | None:
        return self._escalation

    def set_live_corpus_escalation_issue(self, issue_number: int) -> None:
        self._escalation = issue_number

    def clear_live_corpus_escalation_issue(self) -> None:
        self._escalation = None


def _build_loop(
    tmp_path: Path,
    *,
    pr_manager: Any | None = None,
    state: Any | None = None,
    max_drift_attempts: int = 3,
) -> tuple[LiveCorpusReplayLoop, ShadowCorpus, Any, Any]:
    config = HydraFlowConfig(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        repo="hydra/hydraflow",
        live_corpus_max_drift_attempts=max_drift_attempts,
    )
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    corpus = ShadowCorpus(config.data_root / "contract_shadow")
    pr = pr_manager
    if pr is None:
        pr = MagicMock()
        pr.create_issue = AsyncMock(return_value=4242)
        pr.update_issue_body = AsyncMock()
        pr.close_issue = AsyncMock()
    dedup = DedupStore(
        "live_corpus_replay",
        config.data_root / "dedup" / "live_corpus_replay.json",
    )
    state_obj = state if state is not None else _FakeState()
    stop = asyncio.Event()
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=MagicMock(),
        enabled_cb=lambda _: True,
        sleep_fn=AsyncMock(),
    )
    loop = LiveCorpusReplayLoop(
        config=config,
        corpus=corpus,
        pr_manager=pr,
        dedup=dedup,
        deps=deps,
        state=state_obj,
    )
    return loop, corpus, pr, state_obj


@pytest.mark.asyncio
async def test_empty_corpus_returns_ok_with_zero_compared(tmp_path: Path) -> None:
    loop, _, pr, _state = _build_loop(tmp_path)
    result = await loop._do_work()
    assert result == {
        "status": "ok",
        "compared": 0,
        "skipped_no_dispatcher": 0,
        "drifted": 0,
        "errors": 0,
        "filed_issue": None,
        "escalated_issue": None,
        "escalated_signatures": 0,
    }
    pr.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_sample_with_no_dispatcher_is_skipped(tmp_path: Path) -> None:
    loop, corpus, pr, _state = _build_loop(tmp_path)
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "42"],
        stdout='{"state":"OPEN"}\n',
        stderr="",
        exit_code=0,
    )
    result = await loop._do_work()
    assert result["compared"] == 0
    assert result["skipped_no_dispatcher"] == 1
    assert result["drifted"] == 0
    pr.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatcher_match_no_drift(tmp_path: Path) -> None:
    """Fake output equal to sample → compared=1, no drift, no issue."""
    loop, corpus, pr, _state = _build_loop(tmp_path)
    payload = {"state": "OPEN", "mergeable": "MERGEABLE"}
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "42", "--json", "state,mergeable"],
        stdout=json.dumps(payload) + "\n",
        stderr="",
        exit_code=0,
    )

    async def gh_dispatcher(_sample):  # noqa: ANN001
        return payload

    loop.register("github", "gh", gh_dispatcher)
    result = await loop._do_work()
    assert result["compared"] == 1
    assert result["drifted"] == 0
    pr.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatcher_match_with_drift_files_issue(tmp_path: Path) -> None:
    """Fake output diverges → single hydraflow-find issue filed."""
    loop, corpus, pr, _state = _build_loop(tmp_path)
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "42", "--json", "state"],
        stdout='{"state":"MERGED"}\n',
        stderr="",
        exit_code=0,
    )

    async def stale_fake(_sample):  # noqa: ANN001
        return {"state": "OPEN"}  # diverges from sampled "MERGED"

    loop.register("github", "gh", stale_fake)
    result = await loop._do_work()

    assert result["drifted"] == 1
    pr.create_issue.assert_awaited_once()
    call_args = pr.create_issue.await_args
    labels = call_args.kwargs.get("labels") or call_args.args[2]
    assert "hydraflow-find" in labels
    assert "shadow-drift" in labels


@pytest.mark.asyncio
async def test_identical_drift_dedups_across_ticks(tmp_path: Path) -> None:
    loop, corpus, pr, _state = _build_loop(tmp_path)
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "42"],
        stdout='{"state":"MERGED"}\n',
        stderr="",
        exit_code=0,
    )

    async def stale_fake(_sample):  # noqa: ANN001
        return {"state": "OPEN"}

    loop.register("github", "gh", stale_fake)
    first = await loop._do_work()
    second = await loop._do_work()

    assert first["drifted"] == 1
    assert first["filed_issue"] == 4242
    # Second tick still sees drift but dedup suppresses the issue.
    assert second["drifted"] == 1
    assert second["filed_issue"] is None
    pr.create_issue.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_issue_zero_sentinel_does_not_dedup(tmp_path: Path) -> None:
    """create_issue's 0 sentinel must not add the dedup key.

    Regression for issue #9241: a failed gh call returns 0; adding the
    dedup key would suppress re-filing forever without a real issue. The
    next tick must re-attempt (create_issue awaited twice).
    """
    pr = MagicMock()
    pr.create_issue = AsyncMock(return_value=0)
    loop, corpus, _pr, _state = _build_loop(tmp_path, pr_manager=pr)
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "42"],
        stdout='{"state":"MERGED"}\n',
        stderr="",
        exit_code=0,
    )

    async def stale_fake(_sample):  # noqa: ANN001
        return {"state": "OPEN"}

    loop.register("github", "gh", stale_fake)
    first = await loop._do_work()
    second = await loop._do_work()

    assert first["drifted"] == 1
    assert first["filed_issue"] == 0  # sentinel surfaced in status, not tracked
    # Second tick re-attempts because the dedup key was never added.
    assert second["drifted"] == 1
    assert pr.create_issue.await_count == 2


@pytest.mark.asyncio
async def test_dispatcher_raising_is_caught(tmp_path: Path) -> None:
    loop, corpus, pr, _state = _build_loop(tmp_path)
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "1"],
        stdout="",
        stderr="",
        exit_code=0,
    )

    async def angry_dispatcher(_sample):  # noqa: ANN001
        raise RuntimeError("boom")

    loop.register("github", "gh", angry_dispatcher)
    result = await loop._do_work()
    assert result["errors"] == 1
    assert result["drifted"] == 0
    pr.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_kill_switch_short_circuits(tmp_path: Path) -> None:
    loop, corpus, pr, _state = _build_loop(tmp_path)
    loop._enabled_cb = lambda _name: False
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "1"],
        stdout="",
        stderr="",
        exit_code=0,
    )
    result = await loop._do_work()
    assert result == {"status": "disabled"}
    pr.create_issue.assert_not_awaited()


# ---------------------------------------------------------------------------
# Phase 3: 3-attempt escalation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_escalation_fires_after_threshold_attempts(tmp_path: Path) -> None:
    """When the same drift signature survives ``live_corpus_max_drift_attempts``
    consecutive ticks, the loop files a ``hitl-escalation`` issue routed to
    the auto-agent preflight pipeline."""
    pr = MagicMock()
    # Two awaited calls in this test: one drift issue (tick 1), one
    # escalation issue (tick 3 hits the threshold). Ticks 2/3 dedup-skip
    # the drift issue.
    pr.create_issue = AsyncMock(side_effect=[4242, 5555])
    loop, corpus, _pr, _state = _build_loop(
        tmp_path, pr_manager=pr, max_drift_attempts=3
    )
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "42"],
        stdout='{"state":"MERGED"}\n',
        stderr="",
        exit_code=0,
    )

    async def stale_fake(_sample):  # noqa: ANN001
        return {"state": "OPEN"}

    loop.register("github", "gh", stale_fake)

    # Three ticks with identical drift. The third one hits the threshold.
    results = []
    for _ in range(3):
        results.append(await loop._do_work())

    assert results[0]["escalated_signatures"] == 0
    assert results[1]["escalated_signatures"] == 0
    assert results[2]["escalated_signatures"] == 1
    assert results[2]["escalated_issue"] == 5555

    # The escalation issue carries the hitl-escalation label so the
    # AutoAgentPreflightLoop picks it up.
    escalation_call = pr.create_issue.await_args_list[-1]
    labels = escalation_call.kwargs.get("labels") or escalation_call.args[2]
    assert "hitl-escalation" in labels
    assert "shadow-drift-stuck" in labels


@pytest.mark.asyncio
async def test_clean_tick_clears_attempt_counters(tmp_path: Path) -> None:
    """When drift resolves (clean tick), all attempt counters reset so a
    future re-occurrence of the same signature starts fresh."""
    loop, corpus, _pr, state = _build_loop(tmp_path, max_drift_attempts=3)
    sample_path = corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "1"],
        stdout='{"state":"MERGED"}\n',
        stderr="",
        exit_code=0,
    )
    assert sample_path is not None

    async def stale_fake(_sample):  # noqa: ANN001
        return {"state": "OPEN"}

    loop.register("github", "gh", stale_fake)
    await loop._do_work()
    await loop._do_work()
    # After two ticks of drift, the per-signature counter is 2.
    assert len(state._attempts) == 1
    counter = next(iter(state._attempts.values()))
    assert counter == 2

    # Now the fake catches up — clean tick.
    async def fixed_fake(_sample):  # noqa: ANN001
        return {"state": "MERGED"}

    loop.register("github", "gh", fixed_fake)
    clean = await loop._do_work()

    assert clean["drifted"] == 0
    assert state._attempts == {}, "clean tick must clear all counters"


# ---------------------------------------------------------------------------
# Rollup + auto-close (fix for the #9258..#9335 shadow-drift pile-up): the loop
# keeps ONE open issue, rewrites its body as the diverged set changes, and
# closes it on the first clean tick — instead of filing a new issue per tick.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_changed_drift_set_updates_rollup_not_new_issue(tmp_path: Path) -> None:
    """A *changed* diverged set updates the open rollup body, not a new issue."""
    loop, corpus, pr, state = _build_loop(tmp_path)
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "42"],
        stdout='{"state":"MERGED"}\n',
        stderr="",
        exit_code=0,
    )
    out = {"state": "OPEN"}

    async def stale_fake(_sample):  # noqa: ANN001
        return out

    loop.register("github", "gh", stale_fake)
    first = await loop._do_work()
    assert first["filed_issue"] == 4242
    assert state.get_live_corpus_drift_rollup()["issue_number"] == 4242
    pr.create_issue.assert_awaited_once()

    # Different divergence -> different signature set -> body rewritten in place.
    out = {"state": "CLOSED"}
    second = await loop._do_work()

    assert second["filed_issue"] == 4242  # same rollup issue, not a new one
    pr.create_issue.assert_awaited_once()  # NOT re-filed
    pr.update_issue_body.assert_awaited_once()
    assert pr.update_issue_body.await_args.args[0] == 4242


@pytest.mark.asyncio
async def test_unchanged_drift_set_is_a_noop_write(tmp_path: Path) -> None:
    """Identical diverged set on a later tick performs no GitHub write."""
    loop, corpus, pr, _state = _build_loop(tmp_path)
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "42"],
        stdout='{"state":"MERGED"}\n',
        stderr="",
        exit_code=0,
    )

    async def stale_fake(_sample):  # noqa: ANN001
        return {"state": "OPEN"}

    loop.register("github", "gh", stale_fake)
    await loop._do_work()
    second = await loop._do_work()

    assert second["filed_issue"] is None
    pr.create_issue.assert_awaited_once()
    pr.update_issue_body.assert_not_awaited()


@pytest.mark.asyncio
async def test_clean_tick_closes_open_rollup(tmp_path: Path) -> None:
    """When the fakes catch up, the open rollup issue is closed and cleared."""
    loop, corpus, pr, state = _build_loop(tmp_path)
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "42"],
        stdout='{"state":"MERGED"}\n',
        stderr="",
        exit_code=0,
    )
    out = {"state": "OPEN"}

    async def fake(_sample):  # noqa: ANN001
        return out

    loop.register("github", "gh", fake)
    await loop._do_work()
    assert state.get_live_corpus_drift_rollup()["issue_number"] == 4242

    out = {"state": "MERGED"}  # fake now matches the live sample
    result = await loop._do_work()

    assert result["drifted"] == 0
    pr.close_issue.assert_awaited_once_with(4242)
    assert state.get_live_corpus_drift_rollup() is None


@pytest.mark.asyncio
async def test_escalation_filed_once_and_closed_on_clean_tick(tmp_path: Path) -> None:
    """The shadow-drift-stuck escalation is filed once and closed when clean."""
    pr = MagicMock()
    pr.create_issue = AsyncMock(side_effect=[4242, 7777])
    pr.update_issue_body = AsyncMock()
    pr.close_issue = AsyncMock()
    loop, corpus, _pr, state = _build_loop(
        tmp_path, pr_manager=pr, max_drift_attempts=1
    )
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "42"],
        stdout='{"state":"MERGED"}\n',
        stderr="",
        exit_code=0,
    )
    out = {"state": "OPEN"}

    async def fake(_sample):  # noqa: ANN001
        return out

    loop.register("github", "gh", fake)

    first = await loop._do_work()
    assert first["escalated_issue"] == 7777
    assert state.get_live_corpus_escalation_issue() == 7777

    # Drift persists: escalation must NOT be re-filed (one open escalation).
    await loop._do_work()
    assert pr.create_issue.await_count == 2  # rollup + escalation only

    # Clean tick closes BOTH the rollup and the escalation.
    out = {"state": "MERGED"}
    await loop._do_work()
    assert state.get_live_corpus_escalation_issue() is None
    assert state.get_live_corpus_drift_rollup() is None
    assert pr.close_issue.await_count == 2


@pytest.mark.asyncio
async def test_state_less_path_falls_back_to_dedup_gate(tmp_path: Path) -> None:
    """With no state (state=None), the loop keeps the original dedup-store gate:
    identical drift across ticks files at most one issue."""
    config = HydraFlowConfig(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        repo="hydra/hydraflow",
    )
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    corpus = ShadowCorpus(config.data_root / "contract_shadow")
    pr = MagicMock()
    pr.create_issue = AsyncMock(return_value=4242)
    pr.update_issue_body = AsyncMock()
    pr.close_issue = AsyncMock()
    dedup = DedupStore("live_corpus_replay", config.data_root / "dedup" / "lcr.json")
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=lambda _name: True,
        sleep_fn=AsyncMock(),
    )
    loop = LiveCorpusReplayLoop(
        config=config,
        corpus=corpus,
        pr_manager=pr,
        dedup=dedup,
        deps=deps,
        state=None,
    )
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "42"],
        stdout='{"state":"MERGED"}\n',
        stderr="",
        exit_code=0,
    )

    async def stale_fake(_sample):  # noqa: ANN001
        return {"state": "OPEN"}

    loop.register("github", "gh", stale_fake)
    await loop._do_work()
    await loop._do_work()

    pr.create_issue.assert_awaited_once()


# ---------------------------------------------------------------------------
# Escalation dedup (#9313, preserved from staging): the shadow-drift-stuck
# escalation fires once per drift run, and a clean tick lets a recurrence
# re-escalate. These pass through the state-based rollup path above.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_escalation_dedups_on_subsequent_ticks(tmp_path: Path) -> None:
    """Escalation issue fires exactly once per drift run, not on every tick
    after the threshold.

    Regression for the missing escalation dedup: before the fix, every tick
    past the threshold called _file_escalation_issue, filing a new hitl issue
    each time.
    """
    pr = MagicMock()
    # drift issue (tick 1), escalation issue (tick 3) — ticks 4+ must not
    # file another escalation.
    pr.create_issue = AsyncMock(side_effect=[4242, 5555])
    pr.update_issue_body = AsyncMock()
    pr.close_issue = AsyncMock()
    loop, corpus, _pr, _state = _build_loop(
        tmp_path, pr_manager=pr, max_drift_attempts=3
    )
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "99"],
        stdout='{"state":"MERGED"}\n',
        stderr="",
        exit_code=0,
    )

    async def stale_fake(_sample):  # noqa: ANN001
        return {"state": "OPEN"}

    loop.register("github", "gh", stale_fake)

    # Five ticks — threshold is 3, so ticks 3/4/5 all have the counter at ≥3.
    for _ in range(5):
        await loop._do_work()

    # Only two create_issue calls total: the initial drift issue and one escalation.
    assert pr.create_issue.await_count == 2


# ---------------------------------------------------------------------------
# VOLATILE shape suppression (issue #9354): raw-value drift on live-state
# queries must not generate drift signals; only shape validation failures do.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_volatile_sample_raw_value_diff_does_not_file_issue(
    tmp_path: Path,
) -> None:
    """gh issue list value changes every time an issue is filed.  A dispatcher
    returning a different dict (raw-value divergence) on a VOLATILE shape must
    NOT count as drift — it's expected non-determinism, not a fake gap."""
    loop, corpus, pr, _state = _build_loop(tmp_path)
    corpus.record(
        adapter="github",
        command="gh",
        args=["issue", "list", "--json", "number,title"],
        stdout='[{"number":1,"title":"old title"}]\n',
        stderr="",
        exit_code=0,
    )

    async def live_value_changed(_sample):  # noqa: ANN001
        # Returns a different value — simulates live list changing.
        return [{"number": 1, "title": "new title"}, {"number": 2, "title": "extra"}]

    loop.register("github", "gh", live_value_changed)
    result = await loop._do_work()

    assert result["drifted"] == 0
    pr.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_volatile_sample_shape_failure_does_file_issue(tmp_path: Path) -> None:
    """A shape validation failure on a VOLATILE sample IS real drift — the gh
    schema changed.  The loop must still file an issue when SHAPE_VERDICT_KEY
    is present in the dispatcher output."""
    from contracts.shadow_classifier import SHAPE_VERDICT_KEY

    loop, corpus, pr, _state = _build_loop(tmp_path)
    corpus.record(
        adapter="github",
        command="gh",
        args=["issue", "list", "--json", "number,title"],
        stdout='[{"number":1,"title":"x"}]\n',
        stderr="",
        exit_code=0,
    )

    async def shape_failure_dispatcher(_sample):  # noqa: ANN001
        # Simulates gh_shape_validator returning a shape failure.
        return {
            SHAPE_VERDICT_KEY: True,
            "shape": "GhIssueListItem",
            "subcommand": "issue-list",
            "failure_count": 1,
            "failures": [{"loc": "number", "type": "int_type", "msg": "not int"}],
        }

    loop.register("github", "gh", shape_failure_dispatcher)
    result = await loop._do_work()

    assert result["drifted"] == 1
    pr.create_issue.assert_awaited_once()


@pytest.mark.asyncio
async def test_deterministic_sample_value_diff_still_files_issue(
    tmp_path: Path,
) -> None:
    """DETERMINISTIC shapes (gh pr view) preserve the existing full value-compare
    behaviour — a raw-value difference must still file a drift issue."""
    loop, corpus, pr, _state = _build_loop(tmp_path)
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "42", "--json", "state,number"],
        stdout='{"number":42,"state":"OPEN"}\n',
        stderr="",
        exit_code=0,
    )

    async def stale_fake(_sample):  # noqa: ANN001
        return {"number": 42, "state": "MERGED"}  # value divergence

    loop.register("github", "gh", stale_fake)
    result = await loop._do_work()

    assert result["drifted"] == 1
    pr.create_issue.assert_awaited_once()


@pytest.mark.asyncio
async def test_clean_tick_resets_escalation_dedup(tmp_path: Path) -> None:
    """After a clean tick the escalation is cleared so a future recurrence of
    the same drift can re-escalate."""
    pr = MagicMock()
    pr.create_issue = AsyncMock(side_effect=[4242, 5555, 6666, 7777])
    pr.update_issue_body = AsyncMock()
    pr.close_issue = AsyncMock()
    loop, corpus, _pr, _state = _build_loop(
        tmp_path, pr_manager=pr, max_drift_attempts=3
    )
    corpus.record(
        adapter="github",
        command="gh",
        args=["pr", "view", "7"],
        stdout='{"state":"MERGED"}\n',
        stderr="",
        exit_code=0,
    )

    async def stale_fake(_sample):  # noqa: ANN001
        return {"state": "OPEN"}

    async def fixed_fake(_sample):  # noqa: ANN001
        return {"state": "MERGED"}

    loop.register("github", "gh", stale_fake)
    for _ in range(3):
        await loop._do_work()
    # Escalation is now open.

    # Clean tick — drift stops; the rollup + escalation are closed and cleared.
    loop.register("github", "gh", fixed_fake)
    await loop._do_work()

    # Drift recurs — same signature, but the escalation was cleared.
    loop.register("github", "gh", stale_fake)
    for _ in range(3):
        await loop._do_work()

    # The second drift run should have filed a second escalation.
    escalation_calls = [
        call
        for call in pr.create_issue.await_args_list
        if "hitl-escalation"
        in (call.kwargs.get("labels") or (call.args[2] if len(call.args) > 2 else []))
    ]
    assert len(escalation_calls) == 2, (
        "clean tick should clear the escalation so recurrence can re-escalate"
    )
