#!/usr/bin/env python3
"""Oscillation fingerprint (#10820) — fetch + render CLI.

Thin wrapper around ``stillness.fingerprint`` (the pure logic): pulls issue
history from ``gh``, merge history from ``git``, and the loop registry from
``docs/arch/generated/loops.md``, then writes ONE Markdown report. Read-only —
it never writes to GitHub, never files an issue.

    python scripts/oscillation_fingerprint.py \
        --repo T-rav/hydraflow --weeks 8 \
        --output docs/diagnostics/oscillation-fingerprint.md

Run on demand: this is a diagnostic to *gate* the setpoint-conversion redesign
(#10824), deliberately NOT a background loop — adding a 64th perpetual controller
to a plant whose pathology is loop-overpopulation is the move #10819 argues
against.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from stillness.fingerprint import (  # noqa: E402
    Fingerprint,
    IssueRecord,
    LoopInfo,
    MergeRecord,
    fast_tick_loops,
    finder_activity,
    rank_flux_carriers,
    render_report,
    rework_ratio,
    saturation_markers,
    verdict_flapping,
    weekly_self_sourced_fraction,
)

# The quiet-fortnight probe window from #10819/#10820.
PROBE_START = datetime(2026, 7, 14, tzinfo=UTC)
PROBE_END = datetime(2026, 7, 28, 23, 59, tzinfo=UTC)

# Curated finder-label → loop mapping (the "manual classification" the data-source
# map flagged: there is no structured loop↔issue key). `hydraflow-find` is generic.
_FINDER_TO_LOOP = {
    "sampled-audit": "SampledAuditLoop",
    "cost-budget": "CostBudgetWatcherLoop",
    "cost-budget-exceeded": "CostBudgetWatcherLoop",
    "convergence-oscillation": "ConvergenceOscillationLoop",
}

_KNOWN_GAPS = [
    "**Origin is label-based, not author-based** — the factory files under a "
    "human token, so `hydraflow-find` presence (not the GitHub author) marks "
    "self-sourced work. Documented proxy.",
    "**Per-loop attribution for generic `hydraflow-find`** is not recoverable — "
    "~43 loops share the label with no structured loop↔issue key. Only co-labelled "
    "finders (sampled-audit, cost-budget, convergence-oscillation) split cleanly.",
    "**Credit-pause windows are not persisted** — orchestrator credit pauses live "
    "in memory/logs only, so post-saturation windup can only be inferred from "
    "cost-budget cap issues (which are empty when `daily_cost_budget_usd` is unset).",
    "**Per-loop 'signal read' classification** (incident/poll/merge/tests/staleness) "
    "is not structured metadata — it must be read from loop docstrings.",
]


def _run(cmd: list[str]) -> str:
    return subprocess.run(
        cmd, check=True, capture_output=True, text=True, timeout=120
    ).stdout


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fetch_issues(repo: str, since: datetime, limit: int) -> list[IssueRecord]:
    out = _run(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "all",
            "--limit",
            str(limit),
            "--json",
            "number,labels,author,createdAt,closedAt",
            "--search",
            f"created:>={since:%Y-%m-%d}",
        ]
    )
    records = []
    for raw in json.loads(out):
        records.append(
            IssueRecord(
                number=raw["number"],
                created_at=_parse_dt(raw["createdAt"]),
                labels=tuple(sorted(lbl["name"] for lbl in raw.get("labels", []))),
                author=(raw.get("author") or {}).get("login", "unknown"),
                closed_at=_parse_dt(raw["closedAt"]) if raw.get("closedAt") else None,
            )
        )
    return records


def fetch_oscillation_bodies(repo: str, since: datetime) -> dict[int, str]:
    out = _run(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "all",
            "--limit",
            "200",
            "--label",
            "convergence-oscillation",
            "--json",
            "number,body",
            "--search",
            f"created:>={since:%Y-%m-%d}",
        ]
    )
    return {raw["number"]: raw.get("body", "") for raw in json.loads(out)}


def fetch_merges(repo_root: Path, ref: str, since: datetime) -> list[MergeRecord]:
    """Per-merge file lists from first-parent history on `ref` (staging).

    Squash-merges are single first-parent commits carrying the PR's files, so
    first-parent + --name-only approximates 'files per merged PR' well.
    """
    out = _run(
        [
            "git",
            "-C",
            str(repo_root),
            "log",
            "--first-parent",
            ref,
            f"--since={since:%Y-%m-%d}",
            "--name-only",
            "--pretty=format:@@@%H|%cI",
        ]
    )
    merges: list[MergeRecord] = []
    sha = ts = None
    paths: list[str] = []
    for line in out.splitlines():
        if line.startswith("@@@"):
            if sha and ts:
                merges.append(
                    MergeRecord(
                        sha=sha, merged_at=_parse_dt(ts), changed_paths=tuple(paths)
                    )
                )
            header = line[3:]
            sha, _, ts = header.partition("|")
            paths = []
        elif line.strip():
            paths.append(line.strip())
    if sha and ts:
        merges.append(
            MergeRecord(sha=sha, merged_at=_parse_dt(ts), changed_paths=tuple(paths))
        )
    return merges


_LOOP_ROW = re.compile(
    r"^\|\s*\*\*(?P<name>\w+)\*\*\s*\|\s*`(?P<mod>[^`]+)`\s*\|\s*(?P<tick>[^|]+)\|"
)


def parse_loops(loops_md: Path) -> list[LoopInfo]:
    loops: list[LoopInfo] = []
    for line in loops_md.read_text(encoding="utf-8").splitlines():
        m = _LOOP_ROW.match(line)
        if not m:
            continue
        tick_raw = m.group("tick").strip()
        tick = int(tick_raw) if tick_raw.isdigit() else None
        loops.append(
            LoopInfo(name=m.group("name"), module=m.group("mod"), tick_seconds=tick)
        )
    return loops


def build_fingerprint(
    issues: list[IssueRecord],
    osc_bodies: dict[int, str],
    merges: list[MergeRecord],
    loops: list[LoopInfo],
    *,
    now: datetime,
    weeks: int,
) -> Fingerprint:
    escalations = [i for i in issues if "convergence-oscillation" in i.labels]
    finders = finder_activity(issues, now=now, weeks=weeks)
    flapping = verdict_flapping(
        escalations, osc_bodies, probe_start=PROBE_START, probe_end=PROBE_END
    )
    loops_by_name = {lp.name: lp for lp in loops}
    loops_by_finder = {
        finder: loops_by_name[name]
        for finder, name in _FINDER_TO_LOOP.items()
        if name in loops_by_name
    }
    return Fingerprint(
        generated_at=now,
        weeks=weeks,
        self_series=weekly_self_sourced_fraction(issues, now=now, weeks=weeks),
        rework=rework_ratio(merges, now=now, weeks=weeks),
        flapping=flapping,
        finders=finders,
        saturation=saturation_markers(issues),
        fast_ticks=fast_tick_loops(loops),
        carriers=rank_flux_carriers(finders, flapping, loops_by_finder),
        gaps=_KNOWN_GAPS,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default="T-rav/hydraflow")
    ap.add_argument("--weeks", type=int, default=8)
    ap.add_argument("--ref", default="origin/staging")
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--output", type=Path, default=None)
    ap.add_argument(
        "--now", default=None, help="ISO override for the window end (testing)"
    )
    args = ap.parse_args(argv)

    now = _parse_dt(args.now) if args.now else datetime.now(UTC)
    since = now - timedelta(weeks=args.weeks)
    repo_root = Path(__file__).resolve().parent.parent

    print(
        f"Fetching {args.weeks}wk of telemetry (since {since:%Y-%m-%d})…",
        file=sys.stderr,
    )
    issues = fetch_issues(args.repo, since, args.limit)
    osc_bodies = fetch_oscillation_bodies(args.repo, since)
    merges = fetch_merges(repo_root, args.ref, since)
    loops = parse_loops(repo_root / "docs" / "arch" / "generated" / "loops.md")
    print(
        f"  {len(issues)} issues, {len(merges)} merges, {len(loops)} loops",
        file=sys.stderr,
    )

    fp = build_fingerprint(issues, osc_bodies, merges, loops, now=now, weeks=args.weeks)
    report = render_report(fp)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
