#!/usr/bin/env python3
"""Loop-interaction map (#10823) — fetch + render CLI.

Thin wrapper around ``stillness.interaction``: pulls per-merge churn from
``git log --numstat`` and writes ONE Markdown report. Read-only. On-demand
diagnostic (not a loop — same reasoning as #10820).

    python scripts/loop_interaction_map.py --weeks 8 \
        --output docs/diagnostics/loop-interaction-map.md
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from stillness.interaction import (  # noqa: E402
    FileChurn,
    MergeChurn,
    build_interaction_map,
    render_report,
)


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fetch_churn(repo_root: Path, ref: str, since: datetime) -> list[MergeChurn]:
    out = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "log",
            "--first-parent",
            ref,
            f"--since={since:%Y-%m-%d}",
            "--numstat",
            "--pretty=format:@@@%H|%cI",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    ).stdout
    merges: list[MergeChurn] = []
    sha = ts = None
    files: list[FileChurn] = []
    for line in out.splitlines():
        if line.startswith("@@@"):
            if sha and ts:
                merges.append(
                    MergeChurn(sha=sha, merged_at=_parse_dt(ts), files=tuple(files))
                )
            sha, _, ts = line[3:].partition("|")
            files = []
        elif line.strip():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            add_s, del_s, path = parts
            # Binary files report "-\t-\tpath"; count them as no line churn.
            added = int(add_s) if add_s.isdigit() else 0
            deleted = int(del_s) if del_s.isdigit() else 0
            files.append(FileChurn(path=path.strip(), added=added, deleted=deleted))
    if sha and ts:
        merges.append(MergeChurn(sha=sha, merged_at=_parse_dt(ts), files=tuple(files)))
    return merges


def _god_file_modules(repo_root: Path) -> set[str]:
    """The current concentration god-files (best-effort; empty if unavailable)."""
    try:
        from erosion.concentration import compute, extract_file_import_graph

        finding = compute(extract_file_import_graph(repo_root / "src"))
        return {gm.module for gm in finding.god_modules}
    except Exception:  # noqa: BLE001 — cross-ref is optional enrichment
        return set()


def _path_to_module(path: str) -> str | None:
    if not path.startswith("src/") or not path.endswith(".py"):
        return None
    rel = path[len("src/") : -len(".py")]
    return ".".join(p for p in rel.split("/") if p != "__init__")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--weeks", type=int, default=8)
    ap.add_argument("--ref", default="origin/staging")
    ap.add_argument("--output", type=Path, default=None)
    ap.add_argument("--now", default=None)
    args = ap.parse_args(argv)

    now = _parse_dt(args.now) if args.now else datetime.now(UTC)
    since = now - timedelta(weeks=args.weeks)
    repo_root = Path(__file__).resolve().parent.parent

    print(f"Fetching {args.weeks}wk of merge churn…", file=sys.stderr)
    merges = fetch_churn(repo_root, args.ref, since)
    im = build_interaction_map(merges, now=now, weeks=args.weeks)

    # Cross-reference: a surface that is BOTH a god-file AND contested is the
    # dangerous combination — high blast radius and fought over.
    gods = _god_file_modules(repo_root)
    both = [s.path for s in im.contested if (_path_to_module(s.path) or "") in gods]
    if both:
        im.cross_refs.append(
            "**God-file AND contested** (high blast radius + fix-as-disturbance): "
            + ", ".join(f"`{p}`" for p in both)
        )
    print(
        f"  {im.total_merges} merges, {len(im.contested)} contested, "
        f"{len(im.couplings)} coupled pairs",
        file=sys.stderr,
    )

    report = render_report(im)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
