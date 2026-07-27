"""Regression test for issue #10622.

Generated-arch **integrity gate**: an extractor that emits an empty/degenerate
artifact (e.g. an events topology with 0 fan-out consumers, a label state
machine with 0 transitions, an ADR xref with 0 citation edges) must trip a
loud CI failure instead of silently passing its lenient paired drift test.

Two prior degenerate artifacts motivated this gate:

* #10619/#10629 — the events extractor modeled a per-``EventType``
  ``subscribe(EventType.X, ...)`` API the fan-out ``EventBus`` never exposed, so
  every event rendered ⚠️ "likely dead" (0 subscribers).
* #10621 — the label state machine had no canonical transition table, so
  ``labels.md`` rendered ``_(no transitions discovered)_`` (0 transitions).

This locks in:

* the **real repo** passes the integrity gate (no degenerate artifacts today);
* a synthetically-degenerate topology **trips** the gate — reverting either the
  events or the labels fix (dropping fan-out-subscribe recognition / the
  canonical transition table) makes the corresponding extractor emit 0 signal,
  which the gate reports as a violation.
"""

from __future__ import annotations

from pathlib import Path

from arch import integrity

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


# --------------------------------------------------------------------------
# The real repo is healthy.
# --------------------------------------------------------------------------


def test_real_repo_passes_integrity_gate() -> None:
    violations = integrity.run_integrity_checks(REPO_ROOT)
    assert violations == [], "\n".join(str(v) for v in violations)


# --------------------------------------------------------------------------
# Reverting the events fix (#10619/#10629) => 0 fan-out subscribers => trip.
# --------------------------------------------------------------------------


def test_degenerate_events_topology_trips_gate(tmp_path: Path) -> None:
    # Publishers exist, but there is no argless ``subscribe()`` fan-out
    # consumer — exactly the shape the pre-#10619 extractor produced (every
    # event flagged dead). Publisher signal is fine; the subscriber signal is 0.
    _write(
        tmp_path,
        "src/widget_loop.py",
        "class WidgetLoop:\n"
        "    def fire(self, bus):\n"
        "        bus.publish(EventType.PR_OPENED, payload={})\n",
    )
    counts = integrity.probe_events(tmp_path)
    assert counts["publisher edges"] >= 1  # publishers still discovered
    assert counts["fan-out subscribers"] == 0  # the degenerate signal

    violations = integrity.evaluate_artifact("events.md", counts)
    signals = {v.signal for v in violations}
    assert "fan-out subscribers" in signals
    assert "publisher edges" not in signals


def test_healthy_events_topology_passes_gate(tmp_path: Path) -> None:
    # A publish + an argless fan-out subscribe() => both signals present.
    _write(
        tmp_path,
        "src/widget_loop.py",
        "class WidgetLoop:\n"
        "    def fire(self, bus):\n"
        "        bus.publish(EventType.PR_OPENED, payload={})\n"
        "    def consume(self, bus):\n"
        "        queue = bus.subscribe()\n",
    )
    counts = integrity.probe_events(tmp_path)
    assert counts["fan-out subscribers"] >= 1
    assert integrity.evaluate_artifact("events.md", counts) == []


# --------------------------------------------------------------------------
# Reverting the labels fix (#10621) => 0 transitions => trip.
# --------------------------------------------------------------------------


def test_degenerate_label_state_machine_trips_gate(tmp_path: Path) -> None:
    # No canonical LABEL_TRANSITIONS table anywhere under src/ => 0 transitions.
    _write(tmp_path, "src/pr_manager.py", "x = 1\n")
    counts = integrity.probe_labels(tmp_path)
    assert counts["transitions"] == 0

    violations = integrity.evaluate_artifact("labels.md", counts)
    assert any(v.signal == "transitions" for v in violations)


def test_healthy_label_state_machine_passes_gate(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/label_transitions.py",
        "LABEL_TRANSITIONS = [\n"
        '    ("hydraflow-ready", "hydraflow-implementing", "agent_started"),\n'
        "]\n",
    )
    counts = integrity.probe_labels(tmp_path)
    assert counts["transitions"] >= 1
    assert integrity.evaluate_artifact("labels.md", counts) == []


# --------------------------------------------------------------------------
# A degenerate ADR xref (0 citation edges) trips too.
# --------------------------------------------------------------------------


def test_degenerate_adr_xref_trips_gate(tmp_path: Path) -> None:
    _write(tmp_path, "docs/adr/0001-thing.md", "# ADR-0001\n\nNo source refs here.\n")
    counts = integrity.probe_adr_xref(tmp_path)
    assert counts["ADR->module citation edges"] == 0

    violations = integrity.evaluate_artifact("adr_xref.md", counts)
    assert any(v.signal == "ADR->module citation edges" for v in violations)


def test_healthy_adr_xref_passes_gate(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "docs/adr/0001-thing.md",
        "# ADR-0001\n\nGoverns `src/widget_loop.py:WidgetLoop`.\n",
    )
    counts = integrity.probe_adr_xref(tmp_path)
    assert counts["ADR->module citation edges"] >= 1
    assert integrity.evaluate_artifact("adr_xref.md", counts) == []
