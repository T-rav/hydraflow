#!/usr/bin/env python3
"""Builder→outcome report — the live join that flips ``outcome_paired`` (#11027/#10855).

ON-DEMAND runner (quiet-week pattern, not a loop). Composes the machinery the
mechanism-B ruling on #11027 prescribed, all of which already shipped:

1. Read the prompt-observatory ledger (each gated prompt's shape tokens, now
   carrying ``issue_number`` — the Phase-1 capture).
2. ``builder_issue_links`` reconciles shapes → REGISTERED builders, abstaining
   on ambiguity (a shape resembling two builders attributes to neither — never
   a confident-but-wrong attribution).
3. Resolve per-issue outcomes and ``pair_builders`` into per-builder snapshots
   (pass rate / retry rate / escape rate / cost-per-success).
4. Render the fitness verdict: ``outcome_paired`` flips True **iff at least
   one builder paired unambiguously with resolved outcomes** — otherwise the
   honest ``False`` of ADR-0130 stands.

V1 OUTCOME COVERAGE (documented heuristic, printed with every run): ``passed``
comes from issue terminal states (CLOSED+COMPLETED ≈ landed;
NOT_PLANNED/DUPLICATE = failed); ``retries`` / ``escaped`` / ``cost`` are not
yet issue-joinable from the exhaust and default to 0/False/0.0 — so pass-rate
is real, while retry/escape/cost columns are placeholders until the
flow-of-record capture sharpens them. The PAIRING itself (which builder owns
which issue's outcome) is exact within the reconciler's stated tolerance.

Read-only; prints the report, writes nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from builder_outcome_pairing import (  # noqa: E402
    IssueOutcome,
    builder_issue_links,
    pair_builders,
)
from prompt_fitness import fitness_summary  # noqa: E402

#: gh `stateReason` values meaning the work did not land.
_FAILED_REASONS = frozenset({"NOT_PLANNED", "DUPLICATE"})


def load_observations(path: Path) -> list[dict[str, object]]:
    """Read observatory JSONL rows, tolerating corrupt/scalar lines."""
    rows: list[dict[str, object]] = []
    if not path.is_file():
        return rows
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def outcomes_from_issue_states(issues_json: Path) -> dict[int, IssueOutcome]:
    """V1 outcome resolution: terminal issue states → pass/fail.

    Open issues are unresolved (absent — dropped by the snapshot, not assumed
    good). retries/escaped/cost stay at their honest zero defaults until the
    exhaust carries an issue-keyed join for them.
    """
    outcomes: dict[int, IssueOutcome] = {}
    rows = json.loads(issues_json.read_text(encoding="utf-8"))
    for row in rows:
        number = row.get("number")
        if not isinstance(number, int):
            continue
        if str(row.get("state", "")).upper() != "CLOSED":
            continue
        reason = str(row.get("stateReason") or "").upper()
        outcomes[number] = IssueOutcome(
            passed=reason not in _FAILED_REASONS,
            retries=0,
            escaped=False,
            cost=0.0,
        )
    return outcomes


def render(
    links: dict[str, set[int]],
    paired: dict[str, object],
    *,
    observations: int,
    outcomes: int,
) -> str:
    """The report: coverage banner, per-builder table, the fitness verdict."""
    out = ["builder→outcome report (#11027 mechanism B / #10855):"]
    out.append(
        f"  observations={observations} · builders-linked={len(links)} · "
        f"resolved-outcomes={outcomes} · builders-paired={len(paired)}"
    )
    out.append(
        "  v1 coverage: pass-rate is real (issue terminal states); "
        "retry/escape/cost are 0-placeholders pending issue-keyed capture."
    )
    if paired:
        out.append("  builder                        pass%   n")
        for builder in sorted(paired):
            snap = paired[builder]
            out.append(
                f"  {builder:<30} {getattr(snap, 'pass_rate', 0.0):>5.0%}"
                f"  {getattr(snap, 'n_samples', 0):>3}"
            )
    fitness = fitness_summary(outcome_paired=bool(paired))
    out.append(
        f"  outcome_paired={fitness.outcome_paired} "
        f"({len(paired)} builder(s) unambiguously paired; ADR-0130 honest-False "
        "stands when zero)"
    )
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Join rubric builders to task outcomes (mechanism B, #11027)."
    )
    parser.add_argument("--observatory", type=Path, required=True)
    parser.add_argument(
        "--issues-json",
        type=Path,
        required=True,
        help="gh issue list --state all --json number,state,stateReason output",
    )
    args = parser.parse_args()

    observations = load_observations(args.observatory)
    links = builder_issue_links(observations)
    outcomes = outcomes_from_issue_states(args.issues_json)
    paired = pair_builders(links, outcomes)
    print(
        render(
            links,
            dict(paired),
            observations=len(observations),
            outcomes=len(outcomes),
        ),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
