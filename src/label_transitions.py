"""Canonical label state-machine transition table (ADR-0002).

Single source of truth for the legal pipeline-stage transitions. Before this
module existed, label moves were implicit in scattered ``swap_pipeline_labels``
call-sites and there was nothing declarative to extract — so
``docs/arch/generated/labels.md`` rendered *(no transitions discovered)* and the
ADR-0002 drift gate was asleep (issue #10621).

Two consumers read this one declaration:

* the **runtime** consults it (``pr_manager.PRManager.transition``) as the
  authoritative set of pipeline-stage labels;
* the **architecture extractor** (``arch.extractors.labels``) reads the
  ``LABEL_TRANSITIONS`` literal verbatim to render
  ``docs/arch/generated/labels.md``.

The drift gate ``tests/architecture/test_label_state_matches_adr0002.py`` diffs
the edges declared here against the Mermaid ``stateDiagram-v2`` block in
``docs/adr/0002-labels-as-state-machine.md``. This table and that diagram MUST
stay in lock-step — a desync is a CI failure by design.

Each entry is ``(from_label, to_label, trigger)`` using the *default*
``hydraflow-*`` label names (the config defaults on
``config.HydraFlowConfig``). Orthogonal markers that coexist with a stage label
rather than being one — ``human-required`` (ADR-0084) and
``hydraflow-in-progress`` (the #10168 build-claim marker) — are deliberately
excluded: ADR-0002 keeps them off the stage-routing map, so they are not edges
in the stage state machine.
"""

from __future__ import annotations

# ADR-0002 pipeline stage state machine. Keep in lock-step with the Mermaid
# block in docs/adr/0002-labels-as-state-machine.md (drift-gated in CI by
# tests/architecture/test_label_state_matches_adr0002.py).
LABEL_TRANSITIONS: list[tuple[str, str, str]] = [
    ("hydraflow-find", "hydraflow-plan", "triage"),
    ("hydraflow-plan", "hydraflow-ready", "plan accepted"),
    ("hydraflow-plan", "hydraflow-hitl", "plan escalation"),
    ("hydraflow-ready", "hydraflow-review", "PR opened"),
    ("hydraflow-ready", "hydraflow-hitl", "implement escalation"),
    ("hydraflow-review", "hydraflow-fixed", "merged"),
    ("hydraflow-review", "hydraflow-hitl", "review escalation"),
    ("hydraflow-hitl", "hydraflow-ready", "human correction"),
    ("hydraflow-hitl", "hydraflow-review", "human re-review"),
]


def pipeline_stage_labels() -> frozenset[str]:
    """Return every stage label that appears in the canonical table."""
    labels: set[str] = set()
    for src, dst, _trigger in LABEL_TRANSITIONS:
        labels.add(src)
        labels.add(dst)
    return frozenset(labels)


def legal_target_labels(from_label: str) -> frozenset[str]:
    """Return the legal one-step destination labels for *from_label*."""
    return frozenset(
        dst for src, dst, _trigger in LABEL_TRANSITIONS if src == from_label
    )


def is_legal_transition(from_label: str, to_label: str) -> bool:
    """Return ``True`` if *from_label* → *to_label* is a declared transition."""
    return to_label in legal_target_labels(from_label)
