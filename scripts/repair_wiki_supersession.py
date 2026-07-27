"""One-shot script: repair the repo wiki's supersession graph (issue #10572).

``WikiCompiler.compile_topic_tracked`` historically wrote a cartesian
``supersedes`` / ``superseded_by`` mapping (issue #10566; the write path is
forward-fixed but the already-corrupted data has not been repaired). This
script walks ``repo_wiki/<owner>/<repo>/<topic>/*.md`` and re-derives the
correct edges from each round's H1 titles — see
``src/wiki_supersession_repair.py`` for the planning logic.

Defaults to a dry-run report: ``repo_wiki/`` is git-tracked, so a stray
invocation must never dirty the tree. Run from the repo root:

    uv run python scripts/repair_wiki_supersession.py --repo T-rav/hydraflow
    uv run python scripts/repair_wiki_supersession.py --repo T-rav/hydraflow --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from wiki_supersession_repair import (  # noqa: E402
    apply_repair_plan,
    discover_topics,
    plan_topic_repair,
    summarize_plan,
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
        "--topic",
        action="append",
        dest="topics",
        help="Limit to this topic (repeatable); default is every topic dir found",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the repair (default is a dry-run report only)",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    tracked_root = Path(args.tracked_root)
    topics = args.topics or discover_topics(tracked_root, args.repo)
    if not topics:
        print(f"no topics found under {tracked_root / args.repo}")
        return 0

    total_touched = 0
    for topic in sorted(topics):
        topic_dir = tracked_root / args.repo / topic
        plan = plan_topic_repair(topic_dir, topic=topic)
        report = summarize_plan(plan)
        print(
            f"{report.topic}: {report.total_superseded} superseded, "
            f"{report.matched} matched, {report.left_on_primary} left-on-primary, "
            f"{report.ambiguous} ambiguous, {report.unclaimed} unclaimed, "
            f"{report.supersedes_lists_rewritten} supersedes-lists-rewritten"
        )
        if args.apply:
            total_touched += apply_repair_plan(plan)

    if args.apply:
        print(f"\napplied: {total_touched} file(s) written")
    else:
        print("\ndry-run only — pass --apply to write changes")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(_parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
