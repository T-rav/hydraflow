#!/usr/bin/env python3
"""Spec-intake review runner — I/O shell over the intake gate (#10830 phase 2).

ON-DEMAND (quiet-week pattern, not a loop — spec arrivals are rare human
events): reads one document, runs :func:`spec_intake_gate.assess` — the
deterministic falsifiability metric always, plus the model reviewer's three
contradiction checks when ``--live`` — prints the verdict, and appends the
content-light row to the intake ledger.

ADVISORY BY CONSTRUCTION: exit code is always 0 on a completed assessment —
the gate records and surfaces, it never blocks (phase-1 ruling; the
cause-control warrant says read the inputs early, not that intake becomes a
new merge gate). ``--live`` spawns one adversarial LLM read; without it the
run is deterministic-only (falsifiability + mush flag).

Usage:
    make spec-intake DOC=docs/superpowers/specs/foo.md
    make spec-intake DOC=... ARGS="--live --model opus"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import HydraFlowConfig  # noqa: E402
from spec_intake_gate import (  # noqa: E402
    SpecIntakeVerdict,
    assess,
    spec_intake_ledger_path,
    verdict_row,
)
from spec_reviewer import cli_spec_reviewer  # noqa: E402


def render_verdict(verdict: SpecIntakeVerdict) -> str:
    """Human-readable verdict — max-severity headline, never a blended score."""
    fals = verdict.falsifiability
    lines = [
        f"# Spec intake — {verdict.subject_id}",
        "",
        f"headline severity: {verdict.headline_severity.value}",
        f"claim density: {fals.claim_density:.2f} "
        f"({fals.checkable_count}/{fals.total_statements} checkable)",
    ]
    row = verdict_row(verdict, recorded_at="")
    if row.mush_flagged:
        lines.append(
            "MUSH FLAG: checkable-claim density below floor — a claim-free "
            "spec passes any stress test perfectly; that is not a pass."
        )
    for c in verdict.contradictions:
        lines.append(
            f"- CONTRADICTION [{c.kind.value}/{c.severity.value}]: "
            f"{c.quote!r} — {c.explanation}"
        )
    for d in verdict.divergences:
        lines.append(f"- DIVERGENCE [{d.kind.value}]: {d.quote!r} — {d.explanation}")
    for a in verdict.load_bearing_assertions:
        lines.append(f"- LOAD-BEARING [{a.severity.value}]: {a.claim}")
    for s in verdict.unstated_assumptions:
        lines.append(f"- UNSTATED ASSUMPTION: {s}")
    if not (
        verdict.contradictions
        or verdict.divergences
        or verdict.load_bearing_assertions
        or verdict.unstated_assumptions
    ):
        lines.append("(no reviewer findings — deterministic metric only)")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stress-test a spec before it becomes a setpoint (#10830)."
    )
    parser.add_argument("document", help="Path to the spec/prose document.")
    parser.add_argument(
        "--subject",
        default=None,
        help="Subject id for the ledger (default: the document's filename).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Spawn the adversarial model reviewer (default: deterministic only).",
    )
    parser.add_argument(
        "--model", default="opus", help="Reviewer model when --live (default: opus)."
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Ledger root (default: HydraFlowConfig().data_root).",
    )
    args = parser.parse_args()

    doc_path = Path(args.document)
    if not doc_path.is_file():
        print(f"no such document: {doc_path}", file=sys.stderr)
        return 2
    document = doc_path.read_text(encoding="utf-8")
    subject_id = args.subject or doc_path.name

    reviewer = None
    if args.live:
        reviewer = cli_spec_reviewer(HydraFlowConfig(), args.model)

    verdict = assess(document, subject_id=subject_id, reviewer=reviewer)
    print(render_verdict(verdict))

    data_root = args.data_root
    if data_root is None:
        data_root = HydraFlowConfig().data_root
    ledger = spec_intake_ledger_path(data_root)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    row = verdict_row(verdict, recorded_at=datetime.now(UTC).isoformat())
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row.to_json_dict()) + "\n")
    print(f"\nledger: {ledger}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
