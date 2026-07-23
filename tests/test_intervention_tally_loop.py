"""Unit tests for InterventionTallyLoop (#10369).

Covers the kill-switches (enabled_cb + config), the timestamp cursor
(baseline priming with no back-analysis + advance), end-to-end sense →
classify → record over a seeded event log + steering map, dedup across
re-ticks, the bounded cheap-LLM classification budget, the free-text LLM
upgrade path (injected fake), the classify-disabled seam, and
reraise_on_credit_or_bug in the classifier except.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from intervention.ledger import InterventionLedger
from intervention_tally_loop import InterventionTallyLoop
from subprocess_util import CreditExhaustedError
from tests.helpers import make_bg_loop_deps


class _Steering:
    def __init__(self, **kw: object) -> None:
        self.guidance = kw.get("guidance")
        self.flow = kw.get("flow", "running")
        self.redo_phase = kw.get("redo_phase")
        self.redo_count = kw.get("redo_count", 0)
        self.last_applied_ts = kw.get("last_applied_ts")


def _make_state(
    initial_ts: str = "", steering: dict[str, Any] | None = None
) -> MagicMock:
    state = MagicMock()
    cursor = {"ts": initial_ts}
    state.get_intervention_tally_last_processed_ts.side_effect = lambda: cursor["ts"]

    def _set(ts: str) -> None:
        cursor["ts"] = ts

    state.set_intervention_tally_last_processed_ts.side_effect = _set
    state.get_all_human_steering.return_value = steering or {}
    state._cursor = cursor
    return state


def _make_dedup() -> MagicMock:
    dedup = MagicMock()
    store: set[str] = set()
    dedup.get.side_effect = lambda: set(store)

    def _set_all(values: set[str]) -> None:
        store.clear()
        store.update(values)

    dedup.set_all.side_effect = _set_all
    return dedup


def _build_loop(
    tmp_path: Path,
    *,
    state: MagicMock,
    classifier: Any = None,
    enabled: bool = True,
    **overrides: Any,
) -> InterventionTallyLoop:
    bg = make_bg_loop_deps(tmp_path, enabled=enabled)
    object.__setattr__(bg.config, "repo_root", tmp_path / "repo")
    object.__setattr__(bg.config, "data_root", tmp_path / "data")
    object.__setattr__(bg.config, "event_log_path", tmp_path / "events.jsonl")
    for key, value in overrides.items():
        object.__setattr__(bg.config, key, value)
    return InterventionTallyLoop(
        config=bg.config,
        state=state,
        dedup=_make_dedup(),
        deps=bg.loop_deps,
        classifier_llm=classifier,
    )


def _write_events(path: Path, events: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


class _FakeClassifier:
    """Injected free-text classifier — returns a scripted JSON verdict."""

    def __init__(self, verdict_json: str) -> None:
        self._verdict = verdict_json
        self.calls = 0

    async def complete(self, prompt: str) -> str:
        self.calls += 1
        return self._verdict


class TestKillSwitches:
    async def test_enabled_cb_off(self, tmp_path: Path) -> None:
        loop = _build_loop(tmp_path, state=_make_state("x"), enabled=False)
        assert (await loop._do_work())["status"] == "disabled"

    async def test_config_disabled(self, tmp_path: Path) -> None:
        loop = _build_loop(
            tmp_path, state=_make_state("x"), intervention_tally_loop_enabled=False
        )
        assert (await loop._do_work())["status"] == "config_disabled"

    async def test_dry_run_noop(self, tmp_path: Path) -> None:
        loop = _build_loop(tmp_path, state=_make_state("x"), dry_run=True)
        assert await loop._do_work() is None


class TestCursor:
    async def test_first_tick_primes_no_back_analysis(self, tmp_path: Path) -> None:
        state = _make_state(initial_ts="")  # fresh install
        # Seed an old event that a back-analysis WOULD pick up:
        _write_events(
            tmp_path / "events.jsonl",
            [
                {
                    "type": "hitl_update",
                    "timestamp": "2020-01-01T00:00:00+00:00",
                    "data": {"action": "resolved"},
                }
            ],
        )
        loop = _build_loop(tmp_path, state=state)
        result = await loop._do_work()
        assert result["status"] == "baseline_established"
        assert state._cursor["ts"]  # primed to now
        assert (
            InterventionLedger(loop._ledger_path).read_all() == []
        )  # nothing recorded


class TestSenseClassifyRecord:
    async def test_records_hitl_and_steering(self, tmp_path: Path) -> None:
        since = "2026-07-23T00:00:00+00:00"
        state = _make_state(
            initial_ts=since,
            steering={
                "11": _Steering(
                    flow="abort", last_applied_ts="2026-07-23T02:05:00+00:00"
                )
            },
        )
        _write_events(
            tmp_path / "events.jsonl",
            [
                {
                    "type": "hitl_update",
                    "timestamp": "2026-07-23T02:00:00+00:00",
                    "data": {"issue": 42, "action": "approved"},
                }
            ],
        )
        loop = _build_loop(tmp_path, state=state)
        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["recorded"] == 2
        rows = InterventionLedger(loop._ledger_path).read_all()
        classes = {r.source: r.intervention_class for r in rows}
        assert classes == {"hitl": "approval", "steering": "unstick"}
        # Cursor advanced past the processed window.
        assert state._cursor["ts"] > since
        # Every row is stamped with a model-version context.
        assert all(r.model_version_context for r in rows)

    async def test_re_tick_dedups(self, tmp_path: Path) -> None:
        since = "2026-07-23T00:00:00+00:00"
        _write_events(
            tmp_path / "events.jsonl",
            [
                {
                    "type": "hitl_update",
                    "timestamp": "2026-07-23T02:00:00+00:00",
                    "data": {"issue": 42, "action": "resolved"},
                }
            ],
        )
        state = _make_state(initial_ts=since)
        loop = _build_loop(tmp_path, state=state)
        first = await loop._do_work()
        assert first["recorded"] == 1
        # Second tick: the cursor advanced, so the same event is now before it.
        second = await loop._do_work()
        assert second["recorded"] == 0
        assert len(InterventionLedger(loop._ledger_path).read_all()) == 1


class TestFreeTextClassification:
    async def test_llm_upgrades_free_text(self, tmp_path: Path) -> None:
        since = "2026-07-23T00:00:00+00:00"
        state = _make_state(
            initial_ts=since,
            steering={
                "11": _Steering(
                    flow="running",
                    guidance="you ignored the ADR — redo per the spec",
                    last_applied_ts="2026-07-23T02:05:00+00:00",
                )
            },
        )
        classifier = _FakeClassifier(
            '{"class": "instruction-violation", "confidence": "high"}'
        )
        loop = _build_loop(tmp_path, state=state, classifier=classifier)
        result = await loop._do_work()
        assert result["llm_classified"] == 1
        assert classifier.calls == 1
        row = InterventionLedger(loop._ledger_path).read_all()[0]
        assert row.intervention_class == "instruction-violation"
        assert row.confidence == "high"
        assert "ADR" in row.notes  # raw text preserved for re-label

    async def test_budget_caps_llm_calls(self, tmp_path: Path) -> None:
        since = "2026-07-23T00:00:00+00:00"
        steering = {
            str(i): _Steering(
                flow="running",
                guidance=f"free text {i}",
                last_applied_ts=f"2026-07-23T02:0{i}:00+00:00",
            )
            for i in range(6)
        }
        state = _make_state(initial_ts=since, steering=steering)
        classifier = _FakeClassifier(
            '{"class": "steering-nudge", "confidence": "medium"}'
        )
        loop = _build_loop(
            tmp_path,
            state=state,
            classifier=classifier,
            intervention_tally_max_classify_per_tick=2,
        )
        result = await loop._do_work()
        # 6 free-text directives, budget 2 → only 2 LLM calls; all 6 recorded.
        assert result["llm_classified"] == 2
        assert classifier.calls == 2
        rows = InterventionLedger(loop._ledger_path).read_all()
        assert len(rows) == 6
        low = [r for r in rows if r.confidence == "low"]
        assert len(low) == 4  # over-budget rows keep low-confidence raw text

    async def test_classify_disabled_keeps_raw(self, tmp_path: Path) -> None:
        since = "2026-07-23T00:00:00+00:00"
        state = _make_state(
            initial_ts=since,
            steering={
                "11": _Steering(
                    flow="running",
                    guidance="some free text",
                    last_applied_ts="2026-07-23T02:05:00+00:00",
                )
            },
        )
        classifier = _FakeClassifier('{"class": "unstick", "confidence": "high"}')
        loop = _build_loop(
            tmp_path,
            state=state,
            classifier=classifier,
            intervention_tally_classify_enabled=False,
        )
        result = await loop._do_work()
        assert result["llm_classified"] == 0
        assert classifier.calls == 0
        row = InterventionLedger(loop._ledger_path).read_all()[0]
        assert row.confidence == "low"
        assert row.intervention_class == "steering-nudge"

    async def test_classifier_credit_exhaustion_reraises(self, tmp_path: Path) -> None:
        since = "2026-07-23T00:00:00+00:00"
        state = _make_state(
            initial_ts=since,
            steering={
                "11": _Steering(
                    flow="running",
                    guidance="free text",
                    last_applied_ts="2026-07-23T02:05:00+00:00",
                )
            },
        )

        class _Boom:
            async def complete(self, prompt: str) -> str:
                raise CreditExhaustedError("out of credits")

        loop = _build_loop(tmp_path, state=state, classifier=_Boom())
        with pytest.raises(CreditExhaustedError):
            await loop._do_work()

    async def test_classifier_transient_failure_keeps_default(
        self, tmp_path: Path
    ) -> None:
        since = "2026-07-23T00:00:00+00:00"
        state = _make_state(
            initial_ts=since,
            steering={
                "11": _Steering(
                    flow="running",
                    guidance="free text",
                    last_applied_ts="2026-07-23T02:05:00+00:00",
                )
            },
        )

        class _Flaky:
            async def complete(self, prompt: str) -> str:
                raise RuntimeError("transient")

        loop = _build_loop(tmp_path, state=state, classifier=_Flaky())
        result = await loop._do_work()  # does not raise — soft failure
        assert result["recorded"] == 1
        row = InterventionLedger(loop._ledger_path).read_all()[0]
        assert row.confidence == "low"  # kept default on failure


class TestReportRendered:
    async def test_report_written(self, tmp_path: Path) -> None:
        since = "2026-07-23T00:00:00+00:00"
        _write_events(
            tmp_path / "events.jsonl",
            [
                {
                    "type": "hitl_update",
                    "timestamp": "2026-07-23T02:00:00+00:00",
                    "data": {"action": "resolved"},
                }
            ],
        )
        loop = _build_loop(tmp_path, state=_make_state(initial_ts=since))
        await loop._do_work()
        report = tmp_path / "repo" / "docs/arch/generated/intervention-tally.md"
        assert report.exists()
        assert "# Intervention tally" in report.read_text()
