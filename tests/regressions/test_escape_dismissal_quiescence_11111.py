"""Regression #11111/#11137/#11144/#11148: a DISMISSED escape goes fully quiet.

The 2026-08-14 idle test showed a dismissal bought exactly one tick of quiet:
dismissal deliberately mutates no ledger row, but three surfaces read only
ledger rows — the diagnoser re-returned INCONCLUSIVE for terminal rows (so
the caller re-filed to a human), selection re-picked dismissed rows every
tick (starving the filing budget), and reconcile could never close the HITL
issues already filed. This pins the quiescence contract end to end at the
pure-function layer.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from escape.auto_diagnose import (  # noqa: E402
    EscapeDiagnosis,
    EscapeDiagnosisLedger,
)
from escape.models import EscapeRecord  # noqa: E402
from escape.surfaces import SurfacedIssue  # noqa: E402
from escape_ledger_loop import (  # noqa: E402
    SURFACE_REASON_AGING,
    SURFACE_REASON_LOW_CONFIDENCE,
    answered_surfacings,
    apply_ask_budget,
    eligible_findings,
    surfacing_fingerprint,
)

_NOW = datetime(2026, 8, 14, tzinfo=UTC)


def _record(rid: str) -> EscapeRecord:
    return EscapeRecord(
        id=rid,
        detected_at="2026-01-01T00:00:00+00:00",
        detection_source="bug-issue",
        detection_ref=rid.split(":", 1)[-1],
        originating_pr=None,
        originating_merge_sha="",
        merged_at="",
        time_to_detection_hours=None,
        attribution_method="fixes-chain",
        attribution_confidence="low",
        encoded_as="none-yet",
        notes="",
    )


def test_sidecar_re_reports_recorded_verdict(tmp_path: Path) -> None:
    ledger = EscapeDiagnosisLedger(tmp_path / "d.jsonl")
    ledger.append_diagnosis("bug-issue:a", EscapeDiagnosis.DISMISSED, "docs-only")
    verdict = ledger.verdict_for("bug-issue:a")
    assert verdict is not None
    assert verdict[0] is EscapeDiagnosis.DISMISSED  # never INCONCLUSIVE again


def test_dismissed_row_never_selected_and_never_occupies_budget() -> None:
    dismissed, genuine = _record("bug-issue:dead"), _record("bug-issue:live")
    eligible = eligible_findings(
        [dismissed, genuine],
        now=_NOW,
        aging_threshold_hours=0.0,  # eligible under BOTH reasons
        already_surfaced=set(),
        terminal_ids={"bug-issue:dead"},
    )
    # the #11137 starvation shape
    to_file, _ = apply_ask_budget(eligible, max_per_tick=1)
    assert [r.id for r, _reason in to_file] == ["bug-issue:live"]


def test_dismissal_answers_stranded_hitl_links() -> None:
    links = [
        SurfacedIssue(
            fingerprint=surfacing_fingerprint("bug-issue:a", reason),
            escape_id="bug-issue:a",
            reason=reason,
            issue_number=n,
            filed_at="",
        )
        for n, reason in ((1, SURFACE_REASON_LOW_CONFIDENCE), (2, SURFACE_REASON_AGING))
    ]
    rec = _record("bug-issue:a")  # ledger row untouched: low + none-yet
    answered = answered_surfacings(links, {rec.id: rec}, {"bug-issue:a": "fp"})
    assert answered == links
