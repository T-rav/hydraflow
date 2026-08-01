"""Cross-link an upheld disagreement INTO the escape ledger (#10370).

The ONE deliberate dependency on the sibling ``escape`` package. An upheld
disagreement is a silent escape the gauntlet missed — the spec cross-links it
into the escape ledger as a ``sampled-audit`` detection so the two instruments
share ONE escape count. This REUSES the merged escape-ledger writer + schema
(``escape.ledger.EscapeLedger`` / ``escape.models.EscapeRecord``); it does NOT
fork the ledger. ``EscapeRecord.detection_source`` is a plain ``str`` (only the
mechanical ``EscapeCandidate`` narrows it to a ``Literal``), so the
``sampled-audit`` source value writes through the existing schema unchanged.
"""

from __future__ import annotations

from audit.models import ESCAPE_DETECTION_SOURCE, AuditSample
from escape.models import EscapeRecord, _hours_between


def sample_to_escape_record(sample: AuditSample) -> EscapeRecord:
    """Build the escape-ledger row for an upheld disagreement.

    ``detection_source='sampled-audit'``, ``attribution_method='agent-research'``
    (an adversarial LLM re-review, not a mechanical git signal), medium
    confidence (a human upheld it through adjudication). ``merged_at`` is unknown
    to the auditor at record time, so ``time_to_detection_hours`` stays ``None``
    unless it can be derived — the honest reading, exactly as the escape ledger
    treats an unresolved originating merge.
    """
    ttd = _hours_between("", sample.audited_at)
    return EscapeRecord(
        id=f"{ESCAPE_DETECTION_SOURCE}:{sample.id}",
        detected_at=sample.audited_at,
        detection_source=ESCAPE_DETECTION_SOURCE,
        detection_ref=sample.merge_sha,
        originating_pr=sample.pr_number or None,
        originating_merge_sha=sample.merge_sha,
        merged_at="",
        time_to_detection_hours=ttd,
        attribution_method="agent-research",
        attribution_confidence="medium",
        encoded_as="none-yet",
        notes=(
            "Upheld sampled-audit disagreement — a silent escape the gauntlet "
            f"missed on PR #{sample.pr_number} "
            f"({sample.blast_radius_class} blast-radius class). Cross-linked "
            "from audit_samples.jsonl (#10370)."
        ),
    )
