"""Transient labels for the earlier-adversarial pipeline.

Three short-lived labels mark intra-stage adversarial review activity. They
are applied while an adversarial sub-stage is running and cleared when the
phase completes. Unlike the canonical pipeline labels
(``hydraflow-find``, ``hydraflow-plan``, ``hydraflow-ready``,
``hydraflow-review``, ``hydraflow-hitl``), these
labels do **not** move an issue between pipeline queues — the
``IssueStore`` label map ignores them. They are observable markers for
operators, dashboards, and downstream consumers (event bus, wiki).

Wiring contract (mirrors PR #8733 / commit 17863e4c for entry-evidence):

1. Recognised — exported as ``LABELS_ADVERSARIAL_TRANSIENT`` so callers
   can import a single canonical set.
2. Not stage-routing — deliberately absent from ``IssueStore._build_label_map``;
   carrying one of these labels does not transition the issue.
3. ``review_phase`` skip — defensively listed so any future PR that
   somehow carries an adversarial transient label is not picked up by
   the agent reviewer pipeline (the labels are intra-stage markers, not
   review work).
4. Negative-cache-safe — adversarial loops do not poll for these
   labels; only the owning phase reads/writes them, so no churn.

The labels are listed alphabetically.
"""

from __future__ import annotations

# Intra-stage adversarial review markers (issue-side, not PR-side).
ADVERSARIAL_ASSUMPTION_REVIEW_LABEL = "hydraflow-assumption-review"
ADVERSARIAL_ENSEMBLE_REVIEW_LABEL = "hydraflow-ensemble-review"
ADVERSARIAL_SPEC_GATE_LABEL = "hydraflow-spec-gate"

# Pre-rename spelling of ``ADVERSARIAL_ENSEMBLE_REVIEW_LABEL``. Labels live on
# GitHub issues, not in this repo, so an issue labelled before the ADR-0053
# single-meaning rename still carries the old string. It stays recognised (see
# contract point 3 above: ``review_phase`` must keep skipping it) but is never
# applied — nothing writes it.
LEGACY_ADVERSARIAL_COUNCIL_REVIEW_LABEL = "hydraflow-council-review"

LABELS_ADVERSARIAL_TRANSIENT: frozenset[str] = frozenset(
    {
        ADVERSARIAL_ASSUMPTION_REVIEW_LABEL,
        ADVERSARIAL_ENSEMBLE_REVIEW_LABEL,
        ADVERSARIAL_SPEC_GATE_LABEL,
        LEGACY_ADVERSARIAL_COUNCIL_REVIEW_LABEL,
    }
)

__all__ = [
    "ADVERSARIAL_ASSUMPTION_REVIEW_LABEL",
    "ADVERSARIAL_ENSEMBLE_REVIEW_LABEL",
    "ADVERSARIAL_SPEC_GATE_LABEL",
    "LABELS_ADVERSARIAL_TRANSIENT",
    "LEGACY_ADVERSARIAL_COUNCIL_REVIEW_LABEL",
]
