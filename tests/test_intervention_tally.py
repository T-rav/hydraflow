"""Unit tests for the intervention-tally instruments (#10369).

Pure-core coverage: taxonomy classification (mechanical + free-text + LLM
verdict), the append-only ledger (record + dedup + malformed tolerance), the
metrics (per-100-merges denominator REUSED from escape, by-class with approval
counted separately, per-loop trust table, loops-per-governor, model-version
markers), the source adapters (event log + steering), and the report render.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from intervention import classify, metrics, sources
from intervention.ledger import InterventionLedger
from intervention.models import (
    InterventionCandidate,
    InterventionRecord,
    InterventionSignal,
)
from intervention.report import render_intervention_tally_markdown

# --- classification -------------------------------------------------------


class TestClassification:
    def test_mechanical_hitl_resolution_is_unstick_high(self) -> None:
        sig = InterventionSignal(
            source="hitl", kind="resolved", ts="2026-07-23T01:00:00+00:00"
        )
        cand = classify.classify_one(sig)
        assert cand.intervention_class == "unstick"
        assert cand.confidence == "high"
        assert cand.needs_llm is False

    def test_approval_is_its_own_class(self) -> None:
        sig = InterventionSignal(
            source="hitl", kind="approved", ts="2026-07-23T01:00:00+00:00"
        )
        assert classify.classify_one(sig).intervention_class == "approval"

    def test_steering_abort_maps_to_unstick(self) -> None:
        sig = InterventionSignal(
            source="steering", kind="abort", ts="2026-07-23T01:00:00+00:00"
        )
        assert classify.classify_one(sig).intervention_class == "unstick"

    def test_control_route_reroute_is_objective_correction(self) -> None:
        sig = InterventionSignal(
            source="control-route", kind="reroute", ts="2026-07-23T01:00:00+00:00"
        )
        assert classify.classify_one(sig).intervention_class == "objective-correction"

    def test_free_text_steering_needs_llm_and_keeps_raw(self) -> None:
        sig = InterventionSignal(
            source="steering",
            kind="guidance",
            ts="2026-07-23T01:00:00+00:00",
            free_text="please refocus on the API contract, not the UI",
        )
        cand = classify.classify_one(sig)
        assert cand.needs_llm is True
        assert cand.confidence == "low"
        assert cand.intervention_class == "steering-nudge"
        assert "API contract" in cand.notes  # raw text preserved for re-label

    def test_parse_llm_verdict_valid(self) -> None:
        assert classify.parse_llm_verdict(
            '{"class": "instruction-violation", "confidence": "high"}'
        ) == ("instruction-violation", "high")

    def test_parse_llm_verdict_tolerates_chatty_reply(self) -> None:
        raw = (
            'Sure!\n```json\n{"class": "quality-override", "confidence": "medium"}\n```'
        )
        assert classify.parse_llm_verdict(raw) == ("quality-override", "medium")

    def test_parse_llm_verdict_rejects_out_of_taxonomy(self) -> None:
        assert classify.parse_llm_verdict('{"class": "nonsense"}') is None

    def test_parse_llm_verdict_rejects_garbage(self) -> None:
        assert classify.parse_llm_verdict("not json at all") is None

    def test_apply_verdict_upgrades_and_clears_needs_llm(self) -> None:
        cand = InterventionCandidate(
            source="steering",
            intervention_class="steering-nudge",
            confidence="low",
            ts="2026-07-23T01:00:00+00:00",
            needs_llm=True,
            notes="raw text",
        )
        upgraded = classify.apply_verdict(cand, ("objective-correction", "high"))
        assert upgraded.intervention_class == "objective-correction"
        assert upgraded.confidence == "high"
        assert upgraded.needs_llm is False
        assert upgraded.notes == "raw text"  # raw preserved even after upgrade


# --- ledger ---------------------------------------------------------------


def _rec(
    id_: str, klass: str = "unstick", ts: str = "2026-07-23T01:00:00+00:00"
) -> InterventionRecord:
    return InterventionRecord(
        id=id_,
        ts=ts,
        source="hitl",
        intervention_class=klass,
        confidence="high",
        loop_or_workflow="pipeline",
        issue_or_pr="42",
        model_version_context="sonnet",
        ref=id_,
        notes="",
    )


class TestLedger:
    def test_append_read_roundtrip(self, tmp_path: Path) -> None:
        ledger = InterventionLedger(tmp_path / "l.jsonl")
        ledger.append(_rec("a"))
        ledger.append(_rec("b"))
        rows = ledger.read_all()
        assert [r.id for r in rows] == ["a", "b"]
        assert ledger.existing_ids() == {"a", "b"}

    def test_missing_file_reads_empty(self, tmp_path: Path) -> None:
        assert InterventionLedger(tmp_path / "nope.jsonl").read_all() == []

    def test_class_key_spelled_out_on_disk(self, tmp_path: Path) -> None:
        path = tmp_path / "l.jsonl"
        InterventionLedger(path).append(_rec("a", klass="approval"))
        payload = json.loads(path.read_text().splitlines()[0])
        assert payload["class"] == "approval"
        assert "intervention_class" not in payload

    def test_malformed_line_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "l.jsonl"
        ledger = InterventionLedger(path)
        ledger.append(_rec("a"))
        with path.open("a") as fh:
            fh.write("{ not json\n")
        ledger.append(_rec("b"))
        assert {r.id for r in ledger.read_all()} == {"a", "b"}


# --- metrics --------------------------------------------------------------


class TestMetrics:
    def test_per_100_merges_reuses_escape_formula(self) -> None:
        from escape.metrics import escapes_per_100_merges

        assert metrics.interventions_per_100_merges(3, 150) == escapes_per_100_merges(
            3, 150
        )
        assert metrics.interventions_per_100_merges(5, 0) == 0.0

    def test_by_class_counts(self) -> None:
        recs = [_rec("a", "unstick"), _rec("b", "approval"), _rec("c", "unstick")]
        assert metrics.by_class(recs) == {"unstick": 2, "approval": 1}

    def test_rolling_correction_excludes_approval(self) -> None:
        now = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
        ts = "2026-07-23T01:00:00+00:00"
        recs = [
            _rec("a", "unstick", ts),
            _rec("b", "approval", ts),
            _rec("c", "objective-correction", ts),
        ]
        assert metrics.rolling_count(recs, now) == 3
        assert metrics.rolling_correction_count(recs, now) == 2  # approval excluded

    def test_per_loop_rates_trust_table(self) -> None:
        recs = [
            _rec("a", "unstick"),
            _rec("b", "approval"),
            _rec("c", "unstick"),
        ]
        rows = metrics.per_loop_rates(recs, merge_count=100)
        assert len(rows) == 1
        row = rows[0]
        assert row.loop_or_workflow == "pipeline"
        assert row.total == 3
        assert row.correction == 2
        assert row.approval == 1
        assert row.per_100_merges == 2.0  # 2 corrections / 100 merges * 100

    def test_loops_per_governor(self) -> None:
        assert metrics.loops_per_governor(40, 4.0) == 10.0
        # No daily corrections → whole fleet governed with no correction load.
        assert metrics.loops_per_governor(40, 0.0) == 40.0

    def test_model_version_markers_first_seen_ordered(self) -> None:
        recs = [
            InterventionRecord(
                "a",
                "2026-07-01T00:00:00+00:00",
                "hitl",
                "unstick",
                "high",
                "p",
                "1",
                "sonnet",
                "a",
                "",
            ),
            InterventionRecord(
                "b",
                "2026-07-10T00:00:00+00:00",
                "hitl",
                "unstick",
                "high",
                "p",
                "2",
                "opus",
                "b",
                "",
            ),
            InterventionRecord(
                "c",
                "2026-07-15T00:00:00+00:00",
                "hitl",
                "unstick",
                "high",
                "p",
                "3",
                "sonnet",
                "c",
                "",
            ),
        ]
        markers = metrics.model_version_markers(recs)
        assert markers == [
            ("2026-07-01T00:00:00+00:00", "sonnet"),
            ("2026-07-10T00:00:00+00:00", "opus"),
        ]


# --- sources --------------------------------------------------------------


class TestSources:
    def test_event_log_senses_hitl_resolution(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        lines = [
            {
                "type": "hitl_update",
                "timestamp": "2026-07-23T02:00:00+00:00",
                "data": {"issue": 42, "action": "resolved"},
            },
            # loop-internal noise — NOT a human touch, must be skipped:
            {
                "type": "hitl_update",
                "timestamp": "2026-07-23T02:01:00+00:00",
                "data": {"issue": 42, "action": "hitl_run", "status": "running"},
            },
        ]
        path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
        sigs = sources.signals_from_event_log(
            path, since_ts="2026-07-23T00:00:00+00:00"
        )
        assert sigs is not None
        assert len(sigs) == 1
        assert sigs[0].source == "hitl"
        assert sigs[0].kind == "resolved"

    def test_event_log_cursor_excludes_old(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        path.write_text(
            json.dumps(
                {
                    "type": "hitl_update",
                    "timestamp": "2026-07-23T02:00:00+00:00",
                    "data": {"action": "resolved"},
                }
            )
            + "\n"
        )
        assert (
            sources.signals_from_event_log(path, since_ts="2026-07-23T03:00:00+00:00")
            == []
        )

    def test_event_log_cli_source_override(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        path.write_text(
            json.dumps(
                {
                    "type": "orchestrator_status",
                    "timestamp": "2026-07-23T02:00:00+00:00",
                    "data": {"status": "stopped", "source": "cli"},
                }
            )
            + "\n"
        )
        sigs = sources.signals_from_event_log(
            path, since_ts="2026-07-23T00:00:00+00:00"
        )
        assert sigs and sigs[0].source == "cli"

    def test_event_log_missing_returns_empty(self, tmp_path: Path) -> None:
        assert sources.signals_from_event_log(tmp_path / "nope.jsonl", "") == []

    def test_steering_flow_and_free_text(self) -> None:
        class _S:
            def __init__(self, **kw: object) -> None:
                self.guidance = kw.get("guidance")
                self.flow = kw.get("flow", "running")
                self.redo_phase = kw.get("redo_phase")
                self.redo_count = kw.get("redo_count", 0)
                self.last_applied_ts = kw.get("last_applied_ts")

        steering = {
            "10": _S(flow="abort", last_applied_ts="2026-07-23T02:00:00+00:00"),
            "11": _S(
                flow="running",
                guidance="refocus on X",
                last_applied_ts="2026-07-23T02:05:00+00:00",
            ),
            # stale (before cursor) — skipped:
            "12": _S(flow="abort", last_applied_ts="2026-07-22T00:00:00+00:00"),
            # no flow, no guidance — not an intervention:
            "13": _S(flow="running", last_applied_ts="2026-07-23T02:10:00+00:00"),
        }
        sigs = sources.signals_from_steering(steering, "2026-07-23T00:00:00+00:00")
        kinds = {s.issue_or_pr: s.kind for s in sigs}
        assert kinds == {"10": "abort", "11": "guidance"}

    def test_active_loop_count(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        lines = [
            {
                "type": "background_worker_status",
                "timestamp": "t",
                "data": {"worker": "escape_ledger"},
            },
            {
                "type": "background_worker_status",
                "timestamp": "t",
                "data": {"worker": "erosion_metrics"},
            },
            {
                "type": "background_worker_status",
                "timestamp": "t",
                "data": {"worker": "escape_ledger"},
            },
            {"type": "phase_change", "timestamp": "t", "data": {}},
        ]
        path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
        assert sources.active_loop_count_from_event_log(path) == 2


# --- report ---------------------------------------------------------------


class TestReport:
    def test_render_headline_and_blind_spot(self) -> None:
        now = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
        recs = [
            _rec("a", "unstick", "2026-07-23T01:00:00+00:00"),
            _rec("b", "approval", "2026-07-23T01:00:00+00:00"),
        ]
        md = render_intervention_tally_markdown(
            recs, now=now, merge_count_30d=100, active_loop_count=40
        )
        assert "# Intervention tally" in md
        assert "correction interventions per 100 merges" in md
        assert "loops per governor" in md
        assert "trust table" in md
        assert "Known blind spot" in md
        assert "approval" in md

    def test_render_empty_ledger(self) -> None:
        now = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
        md = render_intervention_tally_markdown(
            [], now=now, merge_count_30d=0, active_loop_count=0
        )
        assert "no interventions recorded" in md
