"""One-shot auditor: tier N-to-1 wiki-merge predecessors by lesson survival.

The runnable ``wiki_lesson_coverage`` tool (#10754/#10758). It answers the
question #10758 raised — *how many of the ``left_on_primary`` predecessors
have silently dropped their lesson?* — by tiering each one:

* ``orphaned``    — has live code anchors, none survive into the live
  successor: a durable lesson that has left the active corpus. **Act on these.**
* ``weak``        — some but not all live anchors survive.
* ``represented`` — every live anchor survives; the merge preserved the lesson.
* ``no_anchor``   — cites no code anchor, so survival can't be measured here.
* ``not_live``    — every cited anchor is a dangling cite (suppressed; reviving
  would re-import broken cites and trip wiki-rot).

Read-only. ``repo_wiki/`` is git-tracked, so this never writes into the
tracked tree — it prints a table and, with ``--json``, writes a verdict
artifact a follow-up sweep can consume. Run from the repo root:

    uv run python scripts/audit_wiki_lesson_coverage.py --repo T-rav/hydraflow
    uv run python scripts/audit_wiki_lesson_coverage.py --repo T-rav/hydraflow \\
        --json docs/wiki/audits/lesson-coverage-report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from wiki_lesson_coverage import (  # noqa: E402
    TIER_NO_ANCHOR,
    TIER_NOT_LIVE,
    TIER_ORPHANED,
    TIER_REPRESENTED,
    TIER_WEAK,
    assess_repo_coverage,
)

_TIER_ORDER = (
    TIER_ORPHANED,
    TIER_WEAK,
    TIER_REPRESENTED,
    TIER_NO_ANCHOR,
    TIER_NOT_LIVE,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        required=True,
        help="owner/repo the tracked wiki is scoped to, e.g. T-rav/hydraflow",
    )
    parser.add_argument(
        "--tracked-root",
        default=str(REPO_ROOT / "repo_wiki"),
        help="Root of the tracked wiki layout (default: repo_wiki/)",
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Checked-out source tree used to resolve anchor liveness "
        "(default: this repo)",
    )
    parser.add_argument(
        "--topic",
        action="append",
        dest="topics",
        help="Limit to this topic (repeatable); default is every topic dir found",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        help="Also write the full verdict report as JSON to this path",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    tracked_root = Path(args.tracked_root)
    repo_root = Path(args.repo_root)
    report = assess_repo_coverage(
        tracked_root, args.repo, repo_root, topics=args.topics
    )

    print(f"lesson-coverage audit — {args.repo}")
    print(f"{'topic':<16} " + " ".join(f"{t:>12}" for t in _TIER_ORDER))
    for topic in report.topics:
        counts = topic.tier_counts
        row = " ".join(f"{counts.get(t, 0):>12}" for t in _TIER_ORDER)
        print(f"{topic.topic:<16} {row}")
    totals = report.tier_counts
    total_row = " ".join(f"{totals.get(t, 0):>12}" for t in _TIER_ORDER)
    print(f"{'TOTAL':<16} {total_row}")

    orphaned = report.orphaned()
    print(f"\norphaned lessons (act on these): {len(orphaned)}")
    for verdict in orphaned:
        anchors = ", ".join(verdict.live_anchors)
        print(
            f"  {verdict.topic}/{verdict.predecessor_id} "
            f"-> {verdict.terminal_id}  live-anchors: {anchors}"
        )

    if args.json_path:
        out_path = Path(args.json_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"\nwrote verdict report to {out_path}")

    return 0


def main(argv: list[str] | None = None) -> int:
    return run(_parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
