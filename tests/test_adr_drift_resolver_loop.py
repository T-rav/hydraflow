"""Unit tests for AdrDriftResolverLoop (#9976).

Covers the DETECT → TRIAGE → RESOLVE → FAIL-CLOSED pipeline: classification
routing to the correct resolve action for each of the 5 verdict classes,
fail-closed behavior on LOW_CONFIDENCE and on a triage-call error, dedup
(one triage per rollup issue), the kill-switch gate, and
``reraise_on_credit_or_bug`` propagation. The TRIAGE LLM boundary
(``AdrDriftTriageLLM``) is always a fake here — no real model calls.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from adr_drift_resolver_loop import AdrDriftResolverLoop
from adr_drift_triage import DriftClassification, TriageVerdict
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from subprocess_util import CreditExhaustedError


def _deps(stop: asyncio.Event, *, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


def _write_adr(adr_dir: Path, *, number: int, title: str, related: list[str]) -> None:
    related_block = ", ".join(f"`{f}`" for f in related)
    body = (
        f"# ADR-{number:04d}: {title}\n\n"
        f"- **Status:** Accepted\n"
        f"- **Date:** 2026-01-01\n"
        f"- **Related:** {related_block}\n\n"
        f"## Context\n\nFixture background.\n\n"
        f"## Decision\n\nFixture decision text.\n"
    )
    (adr_dir / f"{number:04d}-{title.lower()}.md").write_text(body)


def _verdict(classification: DriftClassification, **kw) -> TriageVerdict:
    return TriageVerdict(
        classification=classification,
        rationale=kw.pop("rationale", "fixture rationale"),
        **kw,
    )


def _pr_manager() -> AsyncMock:
    pr = AsyncMock()
    pr.get_pr_diff = AsyncMock(
        return_value="diff --git a/src/agent.py b/src/agent.py\n"
    )
    pr.get_issue_labels = AsyncMock(return_value=["hydraflow-adr-drift"])
    pr.post_comment = AsyncMock(return_value=None)
    pr.close_issue = AsyncMock(return_value=True)
    pr.update_issue_body = AsyncMock(return_value=None)
    pr.add_labels = AsyncMock(return_value=None)
    pr.remove_label = AsyncMock(return_value=None)
    return pr


@pytest.fixture
def loop_env(tmp_path: Path):
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    _write_adr(adr_dir, number=24, title="alpha", related=["src/agent.py"])

    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        repo_root=tmp_path,
        # Loop now defaults OFF (#10540); force ON so this behavioural fixture
        # exercises the resolver rather than short-circuiting config_disabled.
        adr_drift_resolver_loop_enabled=True,
    )

    state = MagicMock()
    state.all_adr_rollups.return_value = {
        "ADR-0024": {"issue_number": 42, "pr_numbers": [8473]},
    }

    dedup = MagicMock()
    dedup.get.return_value = set()

    pr = _pr_manager()

    from adr_index import ADRIndex  # noqa: PLC0415

    triage = MagicMock()
    triage.classify = AsyncMock(return_value=_verdict(DriftClassification.CONSISTENT))

    return cfg, state, pr, dedup, ADRIndex(adr_dir), triage


def _make_loop(
    loop_env, stop: asyncio.Event, *, enabled: bool = True
) -> AdrDriftResolverLoop:
    cfg, state, pr, dedup, idx, triage = loop_env
    return AdrDriftResolverLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=idx,
        triage=triage,
        deps=_deps(stop, enabled=enabled),
    )


class TestWiring:
    def test_worker_name_and_interval(self, loop_env) -> None:
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        assert loop._worker_name == "adr_drift_resolver"
        assert loop._get_default_interval() == 3600

    def test_loop_fitness_is_housekeeping(self, loop_env) -> None:
        from datetime import UTC, datetime

        from loop_fitness import FitnessContext, FitnessKind

        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        ctx = FitnessContext(
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 1, 2, tzinfo=UTC),
        )
        fitness = loop.loop_fitness(ctx)
        assert fitness.kind == FitnessKind.HOUSEKEEPING
        assert fitness.worker_name == "adr_drift_resolver"


class TestKillSwitchAndGates:
    async def test_disabled_by_kill_switch(self, loop_env) -> None:
        cfg, state, pr, dedup, idx, triage = loop_env
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop, enabled=False)
        result = await loop._do_work()
        assert result == {"status": "disabled"}
        triage.classify.assert_not_called()
        pr.close_issue.assert_not_called()

    async def test_disabled_by_config(self, loop_env) -> None:
        cfg, state, pr, dedup, idx, triage = loop_env
        cfg.adr_drift_resolver_loop_enabled = False
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()
        assert result == {"status": "config_disabled"}
        triage.classify.assert_not_called()

    async def test_dry_run_returns_none(self, loop_env) -> None:
        cfg, state, pr, dedup, idx, triage = loop_env
        cfg.dry_run = True
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()
        assert result is None
        triage.classify.assert_not_called()


class TestClassificationRouting:
    async def test_consistent_closes_no_hitl(self, loop_env) -> None:
        cfg, state, pr, dedup, idx, triage = loop_env
        triage.classify = AsyncMock(
            return_value=_verdict(
                DriftClassification.CONSISTENT, rationale="only a caller changed"
            )
        )
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()

        assert result["closed"] == 1
        assert result["relabeled"] == 0
        assert result["escalated"] == 0
        pr.close_issue.assert_awaited_once_with(42, reason="not planned")
        pr.post_comment.assert_awaited_once()
        assert "only a caller changed" in pr.post_comment.await_args.args[1]
        pr.add_labels.assert_not_called()
        pr.update_issue_body.assert_not_called()

    @pytest.mark.parametrize(
        "classification",
        [
            DriftClassification.REAL_DRIFT,
            DriftClassification.OVER_CITATION,
            DriftClassification.DEAD_CITATION,
        ],
    )
    async def test_relabel_classifications_relabel_to_find(
        self, loop_env, classification
    ) -> None:
        cfg, state, pr, dedup, idx, triage = loop_env
        triage.classify = AsyncMock(
            return_value=_verdict(
                classification,
                rationale="the Decision section is now wrong",
                section="Decision",
            )
        )
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()

        assert result["relabeled"] == 1
        assert result["closed"] == 0
        assert result["escalated"] == 0
        pr.close_issue.assert_not_called()
        pr.remove_label.assert_awaited_once_with(42, "hydraflow-adr-drift")
        pr.add_labels.assert_awaited_once_with(42, ["hydraflow-find"])
        pr.update_issue_body.assert_awaited_once()
        body = pr.update_issue_body.await_args.args[1]
        assert "Decision" in body
        assert "the Decision section is now wrong" in body
        pr.post_comment.assert_awaited_once()

    async def test_low_confidence_escalates_never_closes(self, loop_env) -> None:
        cfg, state, pr, dedup, idx, triage = loop_env
        triage.classify = AsyncMock(
            return_value=_verdict(
                DriftClassification.LOW_CONFIDENCE, rationale="ambiguous evidence"
            )
        )
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()

        assert result["escalated"] == 1
        assert result["closed"] == 0
        assert result["relabeled"] == 0
        pr.close_issue.assert_not_called()
        pr.update_issue_body.assert_not_called()
        pr.remove_label.assert_not_called()
        pr.add_labels.assert_awaited_once_with(42, ["hydraflow-hitl-escalation"])
        pr.post_comment.assert_awaited_once()


class TestFailClosed:
    async def test_triage_error_marks_nothing_and_retries_next_tick(
        self, loop_env
    ) -> None:
        cfg, state, pr, dedup, idx, triage = loop_env
        triage.classify = AsyncMock(side_effect=RuntimeError("llm call failed"))
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()

        assert result["errors"] == 1
        assert result["closed"] == 0
        assert result["relabeled"] == 0
        assert result["escalated"] == 0
        pr.close_issue.assert_not_called()
        pr.add_labels.assert_not_called()
        pr.update_issue_body.assert_not_called()
        dedup.set_all.assert_not_called()

    async def test_credit_exhausted_propagates(self, loop_env) -> None:
        cfg, state, pr, dedup, idx, triage = loop_env
        triage.classify = AsyncMock(side_effect=CreditExhaustedError("out of credits"))
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        with pytest.raises(CreditExhaustedError):
            await loop._do_work()

    async def test_unparseable_verdict_is_not_auto_closed(self, loop_env) -> None:
        """A validation error from the triage wrapper is a triage error too —
        FAIL-CLOSED means it never falls through to an implicit close."""
        cfg, state, pr, dedup, idx, triage = loop_env
        triage.classify = AsyncMock(side_effect=ValueError("invalid TriageVerdict"))
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()

        assert result["errors"] == 1
        pr.close_issue.assert_not_called()


class TestDedup:
    async def test_skips_already_triaged_issue(self, loop_env) -> None:
        cfg, state, pr, dedup, idx, triage = loop_env
        dedup.get.return_value = {"adr_drift_resolver:ADR-0024:42"}
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()

        assert result["candidates"] == 0
        triage.classify.assert_not_called()

    async def test_marks_dedup_after_successful_resolve(self, loop_env) -> None:
        cfg, state, pr, dedup, idx, triage = loop_env
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        await loop._do_work()

        dedup.set_all.assert_called_once()
        written = dedup.set_all.call_args.args[0]
        assert "adr_drift_resolver:ADR-0024:42" in written

    async def test_new_issue_number_gets_fresh_triage(self, loop_env) -> None:
        """A previously-closed rollup re-filed under a NEW issue number for the
        same ADR is a fresh fingerprint — not suppressed by the old one."""
        cfg, state, pr, dedup, idx, triage = loop_env
        dedup.get.return_value = {"adr_drift_resolver:ADR-0024:99"}  # stale, old issue
        state.all_adr_rollups.return_value = {
            "ADR-0024": {"issue_number": 42, "pr_numbers": [8473]},  # new issue #42
        }
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()

        assert result["candidates"] == 1
        triage.classify.assert_awaited_once()


class TestCandidateSelection:
    async def test_fleet_keys_without_adr_numbers_are_skipped(self, loop_env) -> None:
        """#10457 — a FLEET-<pr> rollup persisted before this change (or
        otherwise missing ``adr_numbers``) can't be triaged; it's left for
        the auditor's one-shot, human-closed-only fleet handling, exactly
        like before this change."""
        cfg, state, pr, dedup, idx, triage = loop_env
        state.all_adr_rollups.return_value = {
            "FLEET-9603": {"issue_number": 77, "pr_numbers": [9603]},
        }
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()

        assert result["candidates"] == 0
        assert result["fleet_candidates"] == 0
        triage.classify.assert_not_called()

    async def test_fleet_rollup_with_no_issue_number_is_skipped(self, loop_env) -> None:
        """#10457 — a fleet rollup entry missing/zero ``issue_number`` (a
        corrupt or partially-written state entry) can't be triaged; there is
        no GitHub issue to act on."""
        cfg, state, pr, dedup, idx, triage = loop_env
        state.all_adr_rollups.return_value = {
            "FLEET-9603": {
                "issue_number": 0,
                "pr_numbers": [9603],
                "adr_numbers": [24],
            },
        }
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()

        assert result["fleet_candidates"] == 0
        triage.classify.assert_not_called()

    async def test_malformed_fleet_key_is_skipped_not_crashed(self, loop_env) -> None:
        """#10457 — a corrupt ``FLEET-<pr>`` key with a non-numeric PR
        component can't crash a tick; it's treated as neither a per-ADR nor
        a fleet candidate."""
        cfg, state, pr, dedup, idx, triage = loop_env
        state.all_adr_rollups.return_value = {
            "FLEET-not-a-number": {
                "issue_number": 77,
                "pr_numbers": [9603],
                "adr_numbers": [24],
            },
        }
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()

        assert result["candidates"] == 0
        assert result["fleet_candidates"] == 0
        triage.classify.assert_not_called()

    async def test_rollup_with_no_pr_numbers_is_skipped(self, loop_env) -> None:
        cfg, state, pr, dedup, idx, triage = loop_env
        state.all_adr_rollups.return_value = {
            "ADR-0024": {"issue_number": 42, "pr_numbers": []},
        }
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()

        assert result["candidates"] == 0
        triage.classify.assert_not_called()

    async def test_missing_adr_is_skipped_not_crashed(self, loop_env) -> None:
        cfg, state, pr, dedup, idx, triage = loop_env
        state.all_adr_rollups.return_value = {
            "ADR-9999": {"issue_number": 42, "pr_numbers": [8473]},
        }
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()

        assert result["skipped"] == 1
        assert result["triaged"] == 0
        triage.classify.assert_not_called()

    async def test_max_triage_per_tick_caps_llm_calls(self, loop_env) -> None:
        cfg, state, pr, dedup, idx, triage = loop_env
        cfg.adr_drift_resolver_max_triage_per_tick = 1
        state.all_adr_rollups.return_value = {
            "ADR-0024": {"issue_number": 42, "pr_numbers": [8473]},
        }
        # Add a second ADR + rollup so there are 2 candidates this tick.
        adr_dir = Path(cfg.repo_root) / "docs" / "adr"
        _write_adr(adr_dir, number=27, title="beta", related=["src/runner.py"])
        state.all_adr_rollups.return_value = {
            "ADR-0024": {"issue_number": 42, "pr_numbers": [8473]},
            "ADR-0027": {"issue_number": 43, "pr_numbers": [8474]},
        }
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()

        assert result["triaged"] == 1
        assert triage.classify.await_count == 1

    async def test_target_pr_is_most_recent_contributor(self, loop_env) -> None:
        cfg, state, pr, dedup, idx, triage = loop_env
        state.all_adr_rollups.return_value = {
            "ADR-0024": {"issue_number": 42, "pr_numbers": [8473, 8501, 8480]},
        }
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        await loop._do_work()

        pr.get_pr_diff.assert_awaited_once_with(8501)


class TestFleetTriage:
    """#10457 — extend the CONSISTENT auto-close triage to fleet-batched
    drift issues (previously one-shot / human-closed only). Every member
    ADR of the batch is triaged against the SAME PR; the aggregate only
    closes when ALL members classify CONSISTENT (fail-closed: a missing
    member ADR or any triage-call error leaves the WHOLE batch untouched)."""

    def _fleet_env(self, loop_env):
        cfg, state, pr, dedup, idx, triage = loop_env
        _write_adr(
            Path(cfg.repo_root) / "docs" / "adr",
            number=27,
            title="beta",
            related=["src/runner.py"],
        )
        state.all_adr_rollups.return_value = {
            "FLEET-9603": {
                "issue_number": 77,
                "pr_numbers": [9603],
                "adr_numbers": [24, 27],
            },
        }
        return cfg, state, pr, dedup, idx, triage

    async def test_all_consistent_closes_the_batched_issue(self, loop_env) -> None:
        cfg, state, pr, dedup, idx, triage = self._fleet_env(loop_env)
        triage.classify = AsyncMock(
            side_effect=[
                _verdict(DriftClassification.CONSISTENT, rationale="alpha is fine"),
                _verdict(DriftClassification.CONSISTENT, rationale="beta is fine"),
            ]
        )
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()

        assert result["fleet_candidates"] == 1
        assert result["fleet_triaged"] == 1
        assert result["fleet_closed"] == 1
        pr.close_issue.assert_awaited_once_with(77, reason="not planned")
        pr.post_comment.assert_awaited_once()
        comment = pr.post_comment.await_args.args[1]
        assert "alpha is fine" in comment
        assert "beta is fine" in comment

    async def test_one_non_consistent_member_leaves_issue_open(self, loop_env) -> None:
        cfg, state, pr, dedup, idx, triage = self._fleet_env(loop_env)
        triage.classify = AsyncMock(
            side_effect=[
                _verdict(DriftClassification.CONSISTENT, rationale="alpha is fine"),
                _verdict(
                    DriftClassification.REAL_DRIFT,
                    rationale="beta's decision actually changed",
                    section="Decision",
                ),
            ]
        )
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()

        assert result["fleet_triaged"] == 1
        assert result["fleet_closed"] == 0
        pr.close_issue.assert_not_called()
        pr.post_comment.assert_not_called()
        pr.add_labels.assert_not_called()
        pr.update_issue_body.assert_not_called()

    async def test_dedup_marked_when_batch_left_open_after_mixed_verdicts(
        self, loop_env
    ) -> None:
        """A mixed-verdict batch ('left open', not closed) is still a
        DEFINITIVE triage outcome — it must mark dedup so the batch isn't
        re-triaged (and re-billed) every tick just because it didn't
        auto-close. Only a call ERROR (separately tested) withholds the
        dedup mark."""
        cfg, state, pr, dedup, idx, triage = self._fleet_env(loop_env)
        triage.classify = AsyncMock(
            side_effect=[
                _verdict(DriftClassification.CONSISTENT, rationale="alpha is fine"),
                _verdict(
                    DriftClassification.REAL_DRIFT,
                    rationale="beta's decision actually changed",
                    section="Decision",
                ),
            ]
        )
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        await loop._do_work()

        dedup.set_all.assert_called_once()
        written = dedup.set_all.call_args.args[0]
        assert "adr_drift_resolver:FLEET-9603:77" in written

    async def test_missing_member_adr_skips_whole_batch(self, loop_env) -> None:
        """A renumbered/deleted member ADR skips the WHOLE batch without
        spending any triage calls — mirrors the per-ADR missing-ADR skip."""
        cfg, state, pr, dedup, idx, triage = loop_env
        state.all_adr_rollups.return_value = {
            "FLEET-9603": {
                "issue_number": 77,
                "pr_numbers": [9603],
                "adr_numbers": [24, 9999],
            },
        }
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()

        assert result["fleet_skipped"] == 1
        assert result["fleet_triaged"] == 0
        triage.classify.assert_not_called()
        pr.close_issue.assert_not_called()

    async def test_triage_error_leaves_whole_batch_untriaged(self, loop_env) -> None:
        cfg, state, pr, dedup, idx, triage = self._fleet_env(loop_env)
        triage.classify = AsyncMock(
            side_effect=[
                _verdict(DriftClassification.CONSISTENT, rationale="alpha is fine"),
                RuntimeError("llm call failed"),
            ]
        )
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()

        assert result["fleet_errors"] == 1
        assert result["fleet_closed"] == 0
        pr.close_issue.assert_not_called()
        dedup.set_all.assert_not_called()  # FAIL-CLOSED: retried next tick

    async def test_credit_exhausted_propagates(self, loop_env) -> None:
        cfg, state, pr, dedup, idx, triage = self._fleet_env(loop_env)
        triage.classify = AsyncMock(side_effect=CreditExhaustedError("out of credits"))
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        with pytest.raises(CreditExhaustedError):
            await loop._do_work()

    async def test_dedup_marked_after_definitive_resolution(self, loop_env) -> None:
        """Both 'closed' (all CONSISTENT) and 'left open' (mixed verdicts)
        are definitive triage outcomes — dedup is marked either way so the
        batch isn't re-triaged every tick. Only a call ERROR (see above)
        withholds the dedup mark."""
        cfg, state, pr, dedup, idx, triage = self._fleet_env(loop_env)
        triage.classify = AsyncMock(
            side_effect=[
                _verdict(DriftClassification.CONSISTENT, rationale="alpha is fine"),
                _verdict(DriftClassification.CONSISTENT, rationale="beta is fine"),
            ]
        )
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        await loop._do_work()

        dedup.set_all.assert_called_once()
        written = dedup.set_all.call_args.args[0]
        assert "adr_drift_resolver:FLEET-9603:77" in written

    async def test_max_triage_per_tick_is_shared_with_per_adr_triage(
        self, loop_env
    ) -> None:
        """#10457 — the per-tick LLM-call budget (``adr_drift_resolver_max_
        triage_per_tick``) is shared across BOTH the per-ADR and fleet
        loops: a per-ADR candidate that already consumes the budget must
        stop the fleet loop from spending any calls this tick, not just cap
        each loop independently (which would double the effective budget)."""
        cfg, state, pr, dedup, idx, triage = self._fleet_env(loop_env)
        cfg.adr_drift_resolver_max_triage_per_tick = 1
        # A per-ADR candidate (ADR-0024, already seeded by loop_env) plus the
        # fleet batch from _fleet_env — both present in the same tick.
        state.all_adr_rollups.return_value = {
            "ADR-0024": {"issue_number": 42, "pr_numbers": [8473]},
            "FLEET-9603": {
                "issue_number": 77,
                "pr_numbers": [9603],
                "adr_numbers": [24, 27],
            },
        }
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()

        assert result["triaged"] == 1
        assert result["fleet_candidates"] == 1
        assert result["fleet_triaged"] == 0
        assert result["fleet_closed"] == 0
        # Exactly the one call spent on the per-ADR candidate — the fleet
        # batch's two member ADRs never got triaged this tick.
        assert triage.classify.await_count == 1
        pr.close_issue.assert_awaited_once_with(42, reason="not planned")

    async def test_batch_exceeding_remaining_budget_is_deferred_whole(
        self, loop_env
    ) -> None:
        """#10457 — a batch spends one LLM call PER MEMBER ADR, not one call
        per batch. With no per-ADR candidates competing for the budget, a
        2-member batch must still not start when only 1 call's worth of
        budget remains this tick — starting it would spend 2 calls against a
        budget of 1, silently overshooting ``adr_drift_resolver_max_triage_
        per_tick``. The whole batch is deferred to next tick instead."""
        cfg, state, pr, dedup, idx, triage = self._fleet_env(loop_env)
        cfg.adr_drift_resolver_max_triage_per_tick = 1
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()

        assert result["fleet_candidates"] == 1
        assert result["fleet_triaged"] == 0
        assert result["fleet_closed"] == 0
        assert result["fleet_skipped"] == 0
        triage.classify.assert_not_called()
        pr.close_issue.assert_not_called()
        dedup.set_all.assert_not_called()

    async def test_skips_already_triaged_fleet_batch(self, loop_env) -> None:
        """The dedup-skip case flagged by test-adequacy on the prior attempt
        (#10457): mirrors ``TestDedup.test_skips_already_triaged_issue`` for
        the fleet path — a ``FLEET-<pr>`` batch already fingerprinted in the
        dedup store for its CURRENT issue number is excluded from
        ``_fleet_candidates`` — no re-triage, no re-spent LLM calls, every
        tick."""
        cfg, state, pr, dedup, idx, triage = self._fleet_env(loop_env)
        dedup.get.return_value = {"adr_drift_resolver:FLEET-9603:77"}
        stop = asyncio.Event()
        loop = _make_loop(loop_env, stop)
        result = await loop._do_work()

        assert result["fleet_candidates"] == 0
        assert result["fleet_triaged"] == 0
        triage.classify.assert_not_called()
        pr.close_issue.assert_not_called()
