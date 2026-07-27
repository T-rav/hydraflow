"""Regression guard for #10731: a folded-away surfaced id must still reconcile.

The sampled re-audit of PR #10676 flagged a silent escape. #10676 made
``EscapeLedger.read_latest`` collapse by ``detection_ref`` (two-stage
``latest_by_escape``), but ``_reconcile_surfaced_issues`` indexed that collapsed
view by ``id`` (``{r.id: r for r in read_latest()}``). A surfacing link is keyed
by the exact id it was filed under; when a stronger sibling for the SAME commit
lands (a low-confidence ``bug-issue`` row superseded by a ``regression-pin`` row
for the same ``detection_ref``), the surfaced id is folded away, so the id-keyed
view no longer contains it and ``answered_surfacings`` leaves the HITL issue open
forever — even though the commit is now attributed off ``low``.

This is reachable: the two rows carry different ids (``EscapeCandidate.id`` folds
the source in), and detector evolution + cursor re-analysis records the same
commit sha under two sources across ticks — the exact live shape #10654 fixed
for the metric reads. The reconcile path was never given the same treatment.

Guard: ``EscapeLedger.read_latest_index`` maps EVERY id (id-collapsed) to the
row that won its ``detection_ref`` collapse, so the folded-away surfaced id
resolves to the current winning row and the low-confidence surface is answered.
"""

from __future__ import annotations

from pathlib import Path

from escape.ledger import EscapeLedger
from escape.models import EscapeRecord
from escape.surfaces import SurfacedIssue
from escape_ledger_loop import (
    SURFACE_REASON_LOW_CONFIDENCE,
    answered_surfacings,
    surfacing_fingerprint,
)

# One commit sha, detected under two sources across ticks.
_SHA = "abc1234def5678abc1234def5678abc1234def56"


def _row(source: str, *, confidence: str, encoded_as: str = "none-yet") -> EscapeRecord:
    return EscapeRecord(
        id=f"{source}:{_SHA}",
        detected_at="2026-07-20T00:00:00+00:00",
        detection_source=source,
        detection_ref=_SHA,
        originating_pr=None,
        originating_merge_sha="",
        merged_at="",
        time_to_detection_hours=None,
        attribution_method="fixes-chain" if source == "bug-issue" else "regression-pin",
        attribution_confidence=confidence,
        encoded_as=encoded_as,
        notes="",
    )


def _low_confidence_link() -> SurfacedIssue:
    """The link a busy tick filed for the low-confidence ``bug-issue`` row."""
    escape_id = f"bug-issue:{_SHA}"
    return SurfacedIssue(
        fingerprint=surfacing_fingerprint(escape_id, SURFACE_REASON_LOW_CONFIDENCE),
        escape_id=escape_id,
        reason=SURFACE_REASON_LOW_CONFIDENCE,
        issue_number=1,
        filed_at="2026-07-20T00:00:00+00:00",
    )


class TestIssue10731FoldedAwaySurfacingReconcile:
    def test_stronger_sibling_folds_the_surfaced_id_out_of_read_latest(
        self, tmp_path: Path
    ) -> None:
        # Documents the folding: read_latest keeps one row per detection_ref, so
        # the surfaced bug-issue id is not a key in the id-projected view.
        ledger = EscapeLedger(tmp_path / "escape_ledger.jsonl")
        ledger.append(_row("bug-issue", confidence="low"))
        ledger.append(_row("regression-pin", confidence="medium"))

        id_keyed = {r.id: r for r in ledger.read_latest()}

        assert f"bug-issue:{_SHA}" not in id_keyed
        assert f"regression-pin:{_SHA}" in id_keyed

    def test_read_latest_index_maps_the_folded_id_to_the_winning_row(
        self, tmp_path: Path
    ) -> None:
        ledger = EscapeLedger(tmp_path / "escape_ledger.jsonl")
        ledger.append(_row("bug-issue", confidence="low"))
        ledger.append(_row("regression-pin", confidence="medium"))

        index = ledger.read_latest_index()

        # Both sibling ids resolve to the single surviving (medium) row.
        assert index[f"bug-issue:{_SHA}"].detection_source == "regression-pin"
        assert index[f"regression-pin:{_SHA}"].detection_source == "regression-pin"
        assert index[f"bug-issue:{_SHA}"].attribution_confidence == "medium"

    def test_low_confidence_surface_is_answered_via_the_index_not_the_id_view(
        self, tmp_path: Path
    ) -> None:
        ledger = EscapeLedger(tmp_path / "escape_ledger.jsonl")
        ledger.append(_row("bug-issue", confidence="low"))
        ledger.append(_row("regression-pin", confidence="medium"))
        link = _low_confidence_link()

        # The pre-#10731 id-keyed view strands the link (the escape).
        id_keyed = {r.id: r for r in ledger.read_latest()}
        assert answered_surfacings([link], id_keyed) == []

        # The #10731 index answers it: the commit is now attributed off `low`.
        index = ledger.read_latest_index()
        assert answered_surfacings([link], index) == [link]
