"""Generated-arch integrity gate (issue #10622).

The paired per-extractor drift tests verify an artifact matches its source, but
they stay green when the source itself yields an *empty/degenerate* artifact —
the failure mode behind #10619 (events: 0 fan-out subscribers) and #10621
(labels: 0 transitions). This gate runs the real extractors over the live
``src/`` tree and fails when any artifact falls below its declared
minimum-signal floor. Emptiness is an alarm, not a silently-passing state.
"""

from __future__ import annotations

from pathlib import Path

from arch import integrity


def test_real_repo_has_no_degenerate_artifacts(real_repo_root: Path) -> None:
    violations = integrity.run_integrity_checks(real_repo_root)
    assert violations == [], "Degenerate generated-arch artifact(s):\n" + "\n".join(
        f"  - {v}" for v in violations
    )


def test_named_regression_artifacts_all_have_invariants() -> None:
    # The three artifacts the issue calls out by name must each be guarded.
    guarded = {inv.artifact for inv in integrity.INVARIANTS}
    assert {"events.md", "labels.md", "adr_xref.md"} <= guarded


def test_events_fanout_subscriber_invariant_is_declared() -> None:
    # Lock in the specific #10619/#10629 invariant: >=1 fan-out consumer.
    assert any(
        inv.artifact == "events.md" and inv.signal == "fan-out subscribers"
        for inv in integrity.INVARIANTS
    )


def test_labels_transition_invariant_is_declared() -> None:
    # Lock in the specific #10621 invariant: >=1 label transition.
    assert any(
        inv.artifact == "labels.md" and inv.signal == "transitions"
        for inv in integrity.INVARIANTS
    )


def test_every_invariant_signal_is_produced_by_its_probe(real_repo_root: Path) -> None:
    # Guards against a typo'd signal label silently reading 0 (a phantom
    # violation) or, worse, an invariant that can never fire.
    counts = integrity.probe_repo(real_repo_root)
    for inv in integrity.INVARIANTS:
        assert inv.artifact in counts, inv.artifact
        assert inv.signal in counts[inv.artifact], (inv.artifact, inv.signal)


def test_no_invariant_currently_declares_emptiness_expected() -> None:
    # If a future artifact legitimately becomes empty, flip its
    # expected_empty flag deliberately — this test documents that none do today.
    assert not any(inv.expected_empty for inv in integrity.INVARIANTS)


# --- Pure evaluation logic (no repo I/O) -----------------------------------


def test_evaluate_flags_signal_below_minimum() -> None:
    violations = integrity.evaluate({"labels.md": {"transitions": 0, "states": 0}})
    assert any(
        v.artifact == "labels.md" and v.signal == "transitions" and v.observed == 0
        for v in violations
    )


def test_evaluate_passes_when_signal_meets_minimum() -> None:
    assert (
        integrity.evaluate_artifact("labels.md", {"transitions": 9, "states": 6}) == []
    )


def test_evaluate_treats_missing_signal_as_zero_fail_closed() -> None:
    # An artifact absent from the probe map => observed 0 => violation.
    violations = integrity.evaluate({})
    assert violations, "an empty probe map must trip every invariant"
    assert len(violations) == len(integrity.INVARIANTS)


def test_expected_empty_invariant_never_violates() -> None:
    inv = integrity.IntegrityInvariant(
        artifact="x.md", signal="things", expected_empty=True
    )
    assert integrity._violation_for(inv, {"things": 0}) is None


def test_violation_str_names_artifact_signal_and_reason() -> None:
    v = integrity.IntegrityViolation(
        artifact="events.md",
        signal="fan-out subscribers",
        observed=0,
        minimum=1,
        reason="explanation here",
    )
    text = str(v)
    assert "events.md" in text
    assert "fan-out subscribers" in text
    assert "explanation here" in text
