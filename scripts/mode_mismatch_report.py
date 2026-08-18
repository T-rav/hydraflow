#!/usr/bin/env python3
"""Mode-mismatch report runner — I/O shell over the rung-0 engine (#11055).

ON-DEMAND (quiet-week pattern, not a loop): assembles per-issue traces from the
pipeline event log (``events.jsonl``) plus issue terminal states (a JSON file
from ``gh issue list --state all --json number,state,stateReason``), classifies
them with the pure engine (`mode_mismatch`), prints the report, and optionally
appends the verdict ledger.

V1 SIGNAL COVERAGE (documented heuristic, printed with every run): the event
log currently carries **work_started** (any worker/phase/PR event naming the
issue) and **hitl_escalations** (HITL_ESCALATION events naming the issue);
terminal state comes from the issues JSON (CLOSED+COMPLETED ≈ merged,
CLOSED+NOT_PLANNED/DUPLICATE = closed unmerged). ``route_backs``, ``gave_up``
and ``decomposed_after_attempt`` are NOT yet derivable from the exhaust and
default to zero/False — so the v1 wrong-DAG rate is a **LOWER BOUND** (missing
signals can only add wrong-DAG verdicts, never remove them). If even the lower
bound crosses the proceed threshold, rung 1 is solidly justified; a
"vindicated" verdict at v1 is provisional until those signals are captured
(flow-of-record, #11027 family).

Read-only against the event log; writes only the optional ledger.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mode_mismatch import (  # noqa: E402
    DEFAULT_CHURN_THRESHOLD,
    IssueTrace,
    classify,
    discriminating,
    render_report,
    summarize,
    write_ledger,
)

#: Event types that name an issue WITHOUT proving the pipeline worked it —
#: fleet-wide telemetry that happens to carry an issue field. Everything
#: else naming an issue counts as work evidence.
#:
#: v1 shipped an ALLOW-list (``phase_change``/``worker_update``/
#: ``pr_created``/``planner_update``) that contradicted its own docstring
#: ("any worker/phase/PR event naming the issue"). Three of those four types
#: are not emitted by this factory at all, so the runner classified ZERO
#: issues against a 19k-event log and reported "INSUFFICIENT EVIDENCE" — an
#: instrument reading empty because it was miswired, not because the
#: factory is young. A DENY-list fails the safe way: a new event type
#: counts as work by default, so the wrong-DAG rate can only be
#: under-attributed, never silently zero.
_NON_WORK_EVENT_TYPES = frozenset(
    {
        "pipeline_stats",
        "queue_update",
        "background_worker_status",
        "orchestrator_status",
        "system_alert",
        "metrics_update",
        "cost_update",
        # 71k occurrences in the live log — the second most common type, and
        # emitted by EVERY agent phase (triage, review, planner), not just
        # the build lane. Counting it as work would make ``work_started``
        # true for essentially any issue an agent ever touched, which
        # collapses the very distinction this instrument measures. A
        # transcript line proves an agent spoke about the issue, not that
        # the pipeline built it.
        "transcript_line",
    }
)

#: HITL surfacing is recorded as an escalation event where one exists, and
#: otherwise inferred from the issue carrying a HITL stage in its exhaust.
_HITL_EVENT_TYPES = frozenset(
    {"hitl_escalation", "hitl_update", "hitl_item", "human_input_request"}
)

#: gh `stateReason` values that mean "closed without landing the work".
_UNMERGED_REASONS = frozenset({"NOT_PLANNED", "DUPLICATE"})


def _payload_issue(payload: dict[str, object]) -> int | None:
    """The issue an event payload names, under either historical key."""
    for key in ("issue", "issue_number", "issue_id"):
        value = payload.get(key)
        if isinstance(value, int):
            return value
    return None


def load_traces(
    event_log: Path, issues_json: Path
) -> tuple[list[IssueTrace], dict[str, int]]:
    """Assemble traces; returns ``(traces, coverage_counts)`` for the run banner."""
    worked: set[int] = set()
    hitl: defaultdict[int, int] = defaultdict(int)
    scanned = 0
    for raw_line in event_log.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue  # a JSON scalar line is noise, not an event
        scanned += 1
        etype = str(event.get("type", ""))
        # The bus writes the body under "data"; "payload" was the historical
        # key. Reading only "payload" silently matched NOTHING in the live
        # log — the second half of the miswiring that made this instrument
        # report an empty ledger.
        payload = event.get("data")
        if not isinstance(payload, dict):
            payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        issue = _payload_issue(payload)
        if issue is None:
            continue
        if etype in _HITL_EVENT_TYPES:
            hitl[issue] += 1
            worked.add(issue)
        elif etype not in _NON_WORK_EVENT_TYPES:
            worked.add(issue)

    issues = json.loads(issues_json.read_text(encoding="utf-8"))
    traces: list[IssueTrace] = []
    for row in issues:
        number = row.get("number")
        if not isinstance(number, int):
            continue
        closed = str(row.get("state", "")).upper() == "CLOSED"
        reason = str(row.get("stateReason") or "").upper()
        traces.append(
            IssueTrace(
                issue_number=number,
                merged=closed and reason not in _UNMERGED_REASONS,
                closed_unmerged=closed and reason in _UNMERGED_REASONS,
                work_started=number in worked,
                hitl_escalations=hitl.get(number, 0),
            )
        )
    coverage = {
        "events_scanned": scanned,
        "issues_seen_working": len(worked),
        "issues_with_hitl": len(hitl),
        "issues_in_states_file": len(traces),
    }
    return traces, coverage


def main() -> int:
    parser = argparse.ArgumentParser(description="Mode-mismatch rung-0 report (#11055)")
    parser.add_argument("--event-log", type=Path, required=True)
    parser.add_argument(
        "--issues-json",
        type=Path,
        required=True,
        help="gh issue list --state all --json number,state,stateReason output",
    )
    parser.add_argument("--churn-threshold", type=int, default=DEFAULT_CHURN_THRESHOLD)
    parser.add_argument(
        "--ledger-out", type=Path, default=None, help="Append verdict JSONL here"
    )
    args = parser.parse_args()

    traces, coverage = load_traces(args.event_log, args.issues_json)
    verdicts = [
        verdict
        for verdict in (
            classify(trace, churn_threshold=args.churn_threshold) for trace in traces
        )
        if verdict is not None
    ]
    print("v1 signal coverage (documented heuristic — rate is a LOWER BOUND):")
    for key, value in coverage.items():
        print(f"  {key}: {value}")
    print(
        "  pending signals (default 0/False): route_backs, gave_up, "
        "decomposed_after_attempt\n"
    )
    print(
        render_report(
            summarize(verdicts),
            discriminating_signals=discriminating(traces),
        )
    )
    if args.ledger_out is not None:
        written = write_ledger(args.ledger_out, verdicts)
        print(f"ledger: appended {written} rows to {args.ledger_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
