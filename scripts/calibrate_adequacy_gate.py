#!/usr/bin/env python3
"""Test-adequacy gate calibration runner — I/O shell (#11593 seam 2).

The thin loader around the pure engine in ``src/adequacy_calibration.py``. Same
shape as its siblings ``scripts/calibrate_finders.py`` and
``scripts/quiet_week_experiment.py``: an ON-DEMAND instrument (not a loop) that
reads on-disk factory data, runs the engine, and prints what the evidence
supports. It is **read-only** — it never writes into the factory's data root,
never files an issue, and never touches the gate's configuration.

    make calibrate-adequacy-gate
    make calibrate-adequacy-gate ARGS='--since 2026-08-01 --fetch-closing-prs'
    make calibrate-adequacy-gate ARGS='--json --out /tmp/calibration.json'

Three inputs, each degrading honestly when absent:

* **Run corpus** (``--runs-root``, default ``<repo_data_root>/runs``) — every
  ``runs/<issue>/<timestamp>/manifest.json``. Both manifest shapes are parsed
  (legacy ``error`` string and the #11603 structured ``test_adequacy`` block);
  a manifest that will not parse is counted as skipped, never guessed at.
* **Escape ledger** (``--escape-ledger``, default
  ``<data_root>/diagnostics/escape_ledger.jsonl``) — the outcome oracle from
  ADR-0127 Ruling 4. Missing file ⇒ every outcome is unresolvable
  (``escaped=None``) and the report says so, rather than resolving everything
  as clean, which would silently credit the gate for work nobody checked.
* **Closing PRs** (``--fetch-closing-prs`` via ``gh``, or ``--issue-outcomes``
  with a cached JSON map) — the issue→PR join the escape ledger keys on.
  Without it the accept arm cannot resolve at all, and the report reports that.

Read the IDENTIFIABILITY block of the output before any rate: while it says
UNDER-DETERMINED, the numbers describe the corpus but do not license a change
to the gate's strictness.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from adequacy_calibration import (  # noqa: E402
    AdequacyRunRecord,
    CalibrationReport,
    EvidenceGrade,
    GateOutcome,
    IssueOutcome,
    ProportionInterval,
    calibrate,
    parse_run_manifest,
    parse_run_timestamp,
)

logger = logging.getLogger("hydraflow.calibrate_adequacy_gate")


@dataclass(frozen=True)
class IssueFacts:
    """What GitHub knows about one gated issue: its closing PRs and close date.

    ``closed_at`` is what lets the engine age an escape-free reading past the
    escape-detection grace window; without it a clean reading stays unresolved
    rather than being scored good (see ``adequacy_calibration.resolved_escapes``).
    """

    closing_prs: tuple[int, ...] = ()
    closed_at: datetime | None = None


#: Seam for the issue lookup, so tests never shell out to ``gh``.
IssueQuery = Callable[[int], IssueFacts]

#: How long ``gh issue view`` may take before the lookup is abandoned.
GH_TIMEOUT_SECONDS = 30


# --- loaders --------------------------------------------------------------------


def load_run_records(runs_root: Path) -> tuple[list[AdequacyRunRecord], int]:
    """Read every ``<runs_root>/<issue>/<ts>/manifest.json``.

    Returns ``(records, n_skipped)``. A manifest that is unreadable, not JSON,
    or missing its identifying fields is counted in ``n_skipped`` and dropped —
    a truncated write must not take the rest of the corpus with it.
    """
    records: list[AdequacyRunRecord] = []
    skipped = 0
    if not runs_root.is_dir():
        return records, skipped
    for manifest_path in sorted(runs_root.glob("*/*/manifest.json")):
        try:
            raw = json.loads(manifest_path.read_text())
        except (OSError, ValueError):
            skipped += 1
            continue
        record = parse_run_manifest(raw)
        if record is None:
            skipped += 1
            continue
        records.append(record)
    return records, skipped


def load_escaped_prs(ledger_path: Path) -> set[int] | None:
    """PR numbers carrying an attributed escape; ``None`` when the ledger is absent.

    ``None`` is load-bearing: it means "the outcome oracle is unavailable", which
    the caller must NOT collapse into the empty set. An empty set would resolve
    every merged PR as clean and credit the gate for work nothing checked — the
    exact fail-open ADR-0127 Ruling 6 refuses for its endpoint.
    """
    if not ledger_path.is_file():
        return None
    escaped: set[int] = set()
    try:
        lines = ledger_path.read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        pr = row.get("originating_pr") if isinstance(row, dict) else None
        if isinstance(pr, int) and not isinstance(pr, bool):
            escaped.add(pr)
    return escaped


def gh_issue_facts(issue_number: int) -> IssueFacts:
    """Closing PRs + close date for one issue via ``gh``; empty on any failure.

    Read-only, and never raises: a missing/unauthenticated ``gh``, a timeout, or
    a malformed payload all degrade to "we do not know", which the engine then
    treats as unresolvable rather than as clean.
    """
    try:
        completed = subprocess.run(  # noqa: S603 — fixed argv, no shell
            [
                "gh",
                "issue",
                "view",
                str(issue_number),
                "--json",
                "closedAt,closedByPullRequestsReferences",
            ],
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return IssueFacts()
    if completed.returncode != 0:
        return IssueFacts()
    try:
        payload = json.loads(completed.stdout)
    except ValueError:
        return IssueFacts()
    refs = payload.get("closedByPullRequestsReferences") or []
    return IssueFacts(
        closing_prs=tuple(
            r["number"] for r in refs if isinstance(r, dict) and "number" in r
        ),
        closed_at=parse_run_timestamp(payload.get("closedAt")),
    )


def build_issue_outcomes(
    issues: Iterable[int],
    facts: dict[int, IssueFacts],
    escaped_prs: set[int] | None,
) -> list[IssueOutcome]:
    """Join issues → closing PRs → escape attribution.

    ``escaped`` stays ``None`` — the ledger could not be consulted — whenever it
    is unavailable (``escaped_prs is None``) or the issue has no known closing
    PR. Only a known PR checked against a real ledger yields ``True``/``False``,
    and a ``False`` is only a *reading*: ``closed_at`` rides along so the engine
    can hold it unresolved until it has aged past the grace window.
    """
    outcomes: list[IssueOutcome] = []
    for issue in sorted(set(issues)):
        known = facts.get(issue) or IssueFacts()
        escaped: bool | None = None
        if escaped_prs is not None and known.closing_prs:
            escaped = any(pr in escaped_prs for pr in known.closing_prs)
        outcomes.append(
            IssueOutcome(
                issue_number=issue,
                closing_prs=known.closing_prs,
                escaped=escaped,
                closed_at=known.closed_at,
            )
        )
    return outcomes


def resolve_issue_facts(
    issues: Iterable[int],
    *,
    cached: dict[int, IssueFacts] | None,
    query: IssueQuery | None,
) -> dict[int, IssueFacts]:
    """Issue facts, from the cache first and the query for the rest."""
    resolved: dict[int, IssueFacts] = dict(cached or {})
    if query is None:
        return resolved
    for issue in sorted(set(issues)):
        if issue in resolved:
            continue
        resolved[issue] = query(issue)
    return resolved


def _pr_numbers(raw: object) -> tuple[int, ...]:
    """Coerce a cached PR list to ints, dropping anything that is not one.

    A cache row is operator-supplied data, so a junk entry (``"n/a"``, ``null``,
    a nested object) must cost that entry and nothing else. Dropping is the
    honest failure here: an issue left with no closing PR is *unresolvable*,
    which the engine already handles correctly, whereas raising loses the corpus.
    """
    if not isinstance(raw, list):
        return ()
    numbers: list[int] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, (int, str)):
            continue
        try:
            numbers.append(int(item))
        except ValueError:
            continue
    return tuple(numbers)


def load_issue_facts_cache(path: Path) -> dict[int, IssueFacts]:
    """Read a cached issue→facts map; ``{}`` when the file is absent or broken.

    Two accepted row shapes: ``{"prs": […], "closed_at": "…"}`` (full) and a bare
    ``[…]`` PR list (no close date). The bare form is honest but *weaker*: with
    no close date an escape-free reading can never age past the grace window, so
    it stays unresolved rather than being scored good.

    Never raises. A malformed key, row, or PR entry is skipped individually — the
    "or broken" promise has to hold for junk *inside* a well-formed JSON object,
    not only for unparseable JSON, so one hand-edited bad entry cannot take the
    rest of the cache with it.
    """
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    facts: dict[int, IssueFacts] = {}
    for key, value in raw.items():
        try:
            issue = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, list):
            facts[issue] = IssueFacts(closing_prs=_pr_numbers(value))
        elif isinstance(value, dict):
            facts[issue] = IssueFacts(
                closing_prs=_pr_numbers(value.get("prs")),
                closed_at=parse_run_timestamp(value.get("closed_at")),
            )
    return facts


def gated_and_accepted_issues(records: Sequence[AdequacyRunRecord]) -> set[int]:
    """Issues that reached the gate at all — the only ones worth a PR lookup."""
    return {
        r.issue_number for r in records if r.gate_outcome is not GateOutcome.NOT_REACHED
    }


def filter_since(
    records: Sequence[AdequacyRunRecord], since: datetime | None
) -> list[AdequacyRunRecord]:
    """Keep records at or after *since*; everything when *since* is ``None``."""
    if since is None:
        return list(records)
    return [r for r in records if r.recorded_at >= since]


def parse_since(text: str) -> datetime:
    """Parse ``--since`` as ``YYYY-MM-DD`` or ``YYYYMMDD``, UTC midnight."""
    for fmt in ("%Y-%m-%d%z", "%Y%m%d%z"):
        try:
            return datetime.strptime(f"{text}+0000", fmt)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"unparseable --since date: {text!r}")


# --- rendering ------------------------------------------------------------------


def _fmt_interval(interval: ProportionInterval | None) -> str:
    """Render a proportion as ``k/n = p [lo, hi]``; ``n/a`` when undefined."""
    if interval is None:
        return "n/a"
    return (
        f"{interval.k}/{interval.n} = {interval.point:.0%} "
        f"[{interval.low:.0%}, {interval.high:.0%}]"
    )


def render_report(report: CalibrationReport, *, skipped: int = 0) -> str:
    """Human-readable report. Identifiability first, deliberately."""
    lines: list[str] = []
    window = "empty corpus"
    if report.window_start and report.window_end:
        window = (
            f"{report.window_start.date().isoformat()} → "
            f"{report.window_end.date().isoformat()}"
        )
    lines.append(f"Test-adequacy gate calibration ({window})")
    lines.append("=" * 72)

    ident = report.identifiability
    verdict = "UNDER-DETERMINED" if ident.under_determined else "DETERMINED"
    lines.append(f"\nIDENTIFIABILITY: {verdict}")
    lines.append(
        f"  reject arm: {ident.n_rejections_resolved}/{ident.n_rejections} "
        f"resolved   accept arm: {ident.n_acceptances_resolved}/"
        f"{ident.n_acceptances} resolved"
    )
    for reason in ident.reasons:
        lines.append(f"  - {reason}")

    lines.append("\nCORPUS")
    lines.append(
        f"  runs={report.n_runs}  accepted={report.n_accepted}  "
        f"rejected={report.n_rejected}  never-reached-gate={report.n_not_reached}"
        + (f"  skipped={skipped}" if skipped else "")
    )
    lines.append(
        f"  structured (#11603) manifests: {report.n_structured}/{report.n_runs}"
    )
    if report.median_rejection_minutes is not None:
        lines.append(
            f"  rejection cost: median {report.median_rejection_minutes:.0f} min, "
            f"{report.rejection_hours:.1f} agent-hours total"
        )

    lines.append("\nBY VERDICT SOURCE")
    for summary in report.by_verdict_source:
        mix = ", ".join(
            f"{grade.value}={summary.evidence_mix.get(grade, 0)}"
            for grade in EvidenceGrade
        )
        lines.append(
            f"  {summary.verdict_source}: {summary.n_rejections} rejections "
            f"over {summary.n_issues} issues"
        )
        lines.append(f"      recovery            {_fmt_interval(summary.recovery)}")
        lines.append(
            f"      post-rework escape  {_fmt_interval(summary.post_rework_escape)}"
            "   (of the work that EVENTUALLY merged, not the rejected diff)"
        )
        lines.append(
            f"      demonstrated share  {_fmt_interval(summary.demonstrated_share)}"
        )
        lines.append(f"      evidence mix        {mix}")
        lines.append(f"      weak-justification  {summary.n_suspect}")

    stat = report.stationarity
    lines.append("\nDEMAND STATIONARITY (needs no ground truth)")
    if stat.n_repeat_pairs == 0:
        lines.append("  no issue was rejected twice — nothing to compare")
    else:
        mean = "n/a" if stat.mean_jaccard is None else f"{stat.mean_jaccard:.2f}"
        lines.append(
            f"  demanded something entirely new: {_fmt_interval(stat.disjoint_rate)}"
        )
        lines.append(f"  mean substantive overlap between consecutive demands: {mean}")

    anchoring = report.anchoring
    lines.append("\nDEMAND ANCHORING (#11644 — needs no ground truth)")
    if anchoring.n_findings == 0:
        lines.append("  no rejection findings in the window — nothing to grade")
    else:
        lines.append(
            f"  findings naming a code referent: "
            f"{_fmt_interval(anchoring.anchored_share)}"
        )
        lines.append(
            f"  rejections where NOTHING was locatable: "
            f"{anchoring.n_fully_unanchored_rejections}/{anchoring.n_rejections}"
        )

    pinned = report.pinned_demand
    lines.append("\nPINNED DEMAND (#11644 — the bar the retry was actually judged on)")
    if not pinned.enforced:
        lines.append(
            "  NOT ENFORCED in this window: no run carried a pinned demand "
            "(pre-#11644 corpus, or test_adequacy_pin_demand off)"
        )
    else:
        mean = "n/a" if pinned.mean_jaccard is None else f"{pinned.mean_jaccard:.2f}"
        lines.append(
            f"  retries judged against a pin: {pinned.n_pinned_runs}   "
            f"mean overlap with the pin: {mean}"
        )
        lines.append(
            f"  demanded something entirely new: {_fmt_interval(pinned.disjoint_rate)}"
        )
    lines.append(
        f"  findings absorbed as advisory (new AND unanchored): "
        f"{pinned.n_advisory_findings}"
    )

    score = report.accept_arm_score
    lines.append("\nACCEPT-ARM PROPER SCORE (judge_calibration, ADR-0127)")
    if score.n_resolved == 0:
        lines.append("  no resolved outcome — the gate's miss rate is unmeasured")
    else:
        brier = "n/a" if score.brier is None else f"{score.brier:.3f}"
        lines.append(
            f"  n={score.n_resolved}  brier={brier}"
            + ("  [LOW CONFIDENCE]" if score.low_confidence else "")
        )
        lines.append(
            "  NOTE: selective labels — only work the gate PASSED can be scored, "
            "so this bounds looseness, never strictness."
        )

    lines.append(f"\nWEAK-JUSTIFICATION REJECTIONS ({len(report.suspect_rejections)})")
    lines.append(
        "  Lexical proxies for a weak stated reason — read them, do not treat "
        "them as a labelled error set."
    )
    for suspect in report.suspect_rejections:
        reasons = ",".join(r.value for r in suspect.reasons)
        findings = "; ".join(suspect.findings)[:110]
        lines.append(
            f"  #{suspect.issue_number} "
            f"{suspect.recorded_at.date().isoformat()} "
            f"[{suspect.verdict_source}] {reasons}: {findings}"
        )
    return "\n".join(lines)


# --- entrypoint -----------------------------------------------------------------


def _default_roots() -> tuple[Path, Path]:
    """``(runs_root, escape_ledger)`` from live config; cwd-relative on failure."""
    try:
        from config import HydraFlowConfig  # noqa: PLC0415 — optional at import time

        cfg = HydraFlowConfig()
        return (
            cfg.repo_data_path("runs"),
            cfg.data_root / "diagnostics" / "escape_ledger.jsonl",
        )
    except Exception:  # noqa: BLE001 — a config failure must not block --runs-root
        logger.debug("config unavailable; falling back to cwd-relative defaults")
        base = Path.cwd() / ".hydraflow"
        return base / "runs", base / "diagnostics" / "escape_ledger.jsonl"


def build_parser() -> argparse.ArgumentParser:
    """CLI surface for the calibration runner."""
    runs_default, ledger_default = _default_roots()
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--runs-root", type=Path, default=runs_default)
    parser.add_argument("--escape-ledger", type=Path, default=ledger_default)
    parser.add_argument("--since", type=parse_since, default=None)
    parser.add_argument(
        "--issue-outcomes",
        type=Path,
        default=None,
        help=(
            'JSON map {issue: {"prs": [...], "closed_at": "..."}} (or a bare PR '
            "list, which cannot age a clean reading) instead of querying GitHub"
        ),
    )
    parser.add_argument(
        "--fetch-closing-prs",
        action="store_true",
        help="look up closing PRs + close dates with `gh` (read-only, per issue)",
    )
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    parser.add_argument("--out", type=Path, default=None, help="write output to a file")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Load the corpus, run the engine, print the report. Always returns 0.

    Exit status is deliberately not a verdict: this is an instrument, not a
    gate. An under-determined result is a finding, not a failure.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_parser().parse_args(argv)

    records, skipped = load_run_records(args.runs_root)
    records = filter_since(records, args.since)
    escaped_prs = load_escaped_prs(args.escape_ledger)

    cached: dict[int, IssueFacts] | None = None
    if args.issue_outcomes:
        cached = load_issue_facts_cache(args.issue_outcomes)

    issues = gated_and_accepted_issues(records)
    facts = resolve_issue_facts(
        issues,
        cached=cached,
        query=gh_issue_facts if args.fetch_closing_prs else None,
    )
    outcomes = build_issue_outcomes(issues, facts, escaped_prs)

    report = calibrate(records, outcomes, now=datetime.now(UTC))
    text = (
        json.dumps(report.to_json_dict(), indent=2)
        if args.json
        else render_report(report, skipped=skipped)
    )
    if args.out:
        args.out.write_text(text + "\n")
        logger.info("wrote %s", args.out)
    else:
        logger.info("%s", text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
