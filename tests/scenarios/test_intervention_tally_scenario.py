"""MockWorld scenario for InterventionTallyLoop (#10369).

End-to-end over MockWorld + a seeded event log + steering state — the loop
senses the human touches the factory already emits (a HITL resolution from the
persisted event log, a steering directive from ``SteeringState``), classifies
each into the fixed taxonomy (mechanical here; the free-text LLM path is
exercised via an injected fake so nothing shells out to a real ``claude``),
and records deduped rows to the append-only ledger. A re-tick with the cursor
advanced records nothing further (timestamp-cursor dedup). Mirrors
``tests/scenarios/test_escape_ledger_scenario.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from intervention.ledger import InterventionLedger
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops


class _Steering:
    def __init__(self, **kw: object) -> None:
        self.guidance = kw.get("guidance")
        self.flow = kw.get("flow", "running")
        self.redo_phase = kw.get("redo_phase")
        self.redo_count = kw.get("redo_count", 0)
        self.last_applied_ts = kw.get("last_applied_ts")


def _make_state(initial_ts: str, steering: dict[str, Any]) -> MagicMock:
    state = MagicMock()
    cursor = {"ts": initial_ts}
    state.get_intervention_tally_last_processed_ts.side_effect = lambda: cursor["ts"]

    def _set(ts: str) -> None:
        cursor["ts"] = ts

    state.set_intervention_tally_last_processed_ts.side_effect = _set
    state.get_all_human_steering.return_value = steering
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


class _FakeClassifier:
    def __init__(self, verdict: str) -> None:
        self._verdict = verdict
        self.calls = 0

    async def complete(self, prompt: str) -> str:
        self.calls += 1
        return self._verdict


def _seed_event_log(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    events = [
        {
            "type": "hitl_update",
            "timestamp": "2026-07-23T02:00:00+00:00",
            "data": {"issue": 42, "action": "resolved"},
        },
        # heartbeat noise (active-loop count source; not a human touch)
        {
            "type": "background_worker_status",
            "timestamp": "2026-07-23T02:00:05+00:00",
            "data": {"worker": "escape_ledger"},
        },
    ]
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


def _build_loop(tmp_path: Path, state: Any, classifier: Any = None) -> Any:
    from intervention_tally_loop import InterventionTallyLoop
    from tests.helpers import make_bg_loop_deps

    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "repo_root", tmp_path / "repo")
    object.__setattr__(bg.config, "data_root", tmp_path / "data")
    object.__setattr__(bg.config, "event_log_path", tmp_path / "events.jsonl")
    object.__setattr__(bg.config, "intervention_tally_loop_enabled", True)
    return InterventionTallyLoop(
        config=bg.config,
        state=state,
        dedup=_make_dedup(),
        deps=bg.loop_deps,
        classifier_llm=classifier,
    )


class TestInterventionTallyScenario:
    async def test_senses_seeded_hitl_and_steering(self, tmp_path: Path) -> None:
        MockWorld(tmp_path)  # air-gapped fakes wired (parity with sibling scenarios)
        since = "2026-07-23T00:00:00+00:00"
        _seed_event_log(tmp_path / "events.jsonl")
        state = _make_state(
            since,
            {
                "11": _Steering(
                    flow="abort", last_applied_ts="2026-07-23T02:10:00+00:00"
                )
            },
        )
        loop = _build_loop(tmp_path, state)

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["recorded"] == 2
        rows = InterventionLedger(loop._ledger_path).read_all()
        by_source = {r.source: r for r in rows}
        # HITL 'resolved' action maps mechanically to unstick at high confidence.
        assert by_source["hitl"].intervention_class == "unstick"
        assert by_source["hitl"].confidence == "high"
        assert by_source["steering"].intervention_class == "unstick"
        # The rate report was rendered into the repo root.
        report = tmp_path / "repo" / "docs/arch/generated/intervention-tally.md"
        assert report.exists()
        assert "loops per governor" in report.read_text()

    async def test_free_text_steering_classified_with_confidence(
        self, tmp_path: Path
    ) -> None:
        MockWorld(tmp_path)
        since = "2026-07-23T00:00:00+00:00"
        (tmp_path / "events.jsonl").write_text("")  # no event-log touches
        state = _make_state(
            since,
            {
                "11": _Steering(
                    flow="running",
                    guidance="you shipped without the regression test I asked for",
                    last_applied_ts="2026-07-23T02:10:00+00:00",
                )
            },
        )
        classifier = _FakeClassifier(
            '{"class": "instruction-violation", "confidence": "high"}'
        )
        loop = _build_loop(tmp_path, state, classifier=classifier)

        result = await loop._do_work()

        assert result["llm_classified"] == 1
        assert classifier.calls == 1
        row = InterventionLedger(loop._ledger_path).read_all()[0]
        assert row.intervention_class == "instruction-violation"
        assert row.confidence == "high"  # confidence recorded
        assert "regression test" in row.notes  # raw text kept for re-label

    async def test_re_tick_does_not_rerecord(self, tmp_path: Path) -> None:
        MockWorld(tmp_path)
        since = "2026-07-23T00:00:00+00:00"
        _seed_event_log(tmp_path / "events.jsonl")
        state = _make_state(since, {})
        loop = _build_loop(tmp_path, state)

        first = await loop._do_work()
        assert first["recorded"] == 1  # the HITL resolution

        second = await loop._do_work()
        assert second["recorded"] == 0  # cursor advanced past it
        assert len(InterventionLedger(loop._ledger_path).read_all()) == 1
