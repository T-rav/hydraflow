#!/usr/bin/env python3
"""Regenerate the mass (god-file / god-class size) baseline — a deliberate, reviewed act.

The ratchet guard (``tests/architecture/test_mass_ratchet.py``) fails when a NEW
god file or god class appears beyond the committed baseline. Rerun this when a
decomposition landed (so the smaller size is recorded and the next growth is
caught) or when a new oversized class is an accepted decision — never to make
a red ratchet green without deciding.

Two modes:

``--only src/foo.py:Bar`` (repeatable) re-records exactly the named entries and
leaves every other line byte-identical. This is the mode a decomposition PR
wants: a blanket re-snapshot would sweep every other class's unrelated growth
into that PR's diff, recording it as reviewed when nobody reviewed it (#11646).
An entry that has fallen below threshold is dropped rather than updated — the
membership gate catches it again if it ever crosses back.

    python scripts/regen_mass_baseline.py --only src/pr_manager.py:PRManager \\
        --reason "decomposed PRManager promotion cluster"

With no ``--only``, the whole baseline is re-snapshotted. Reserve that for a PR
whose entire diff *is* the baseline advance, so a reviewer can see what grew.

    python scripts/regen_mass_baseline.py --reason "quarterly baseline advance"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_BASELINE = Path("disturbance/baselines/mass.yaml")

_COMMENT = (
    "Grandfathered god files (LOC >= file threshold) and god classes (LOC or "
    "method count >= class thresholds) — the mass sensor (erosion.mass). The "
    "gate flags NEW entries beyond this set; the recorded loc/methods are the "
    "high-water mark the ErosionMetricsLoop's burn-down roster reports growth "
    "against. Refresh one entry with --only so unrelated growth is never "
    "laundered through an unrelated PR. Last moved: {reason}"
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reason", required=True, help="why the baseline is being moved")
    ap.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="KEY",
        help=(
            "re-record just this entry ('src/foo.py' or 'src/foo.py:Bar'); "
            "repeatable. Every other entry stays byte-identical."
        ),
    )
    ap.add_argument(
        "--allow-metric-growth",
        action="store_true",
        help=(
            "record a metric that RISES while another in the same entry FALLS. "
            "Off by default: a class entry holds loc AND methods, so a "
            "re-record for a genuine loc shrink carries methods along at "
            "whatever it currently is, laundering growth nobody reviewed "
            "(#12142). A uniform rise is the documented accepted-growth flow "
            "and is never blocked."
        ),
    )
    ap.add_argument("--src", type=Path, default=Path("src"))
    ap.add_argument("--out", type=Path, default=_BASELINE)
    args = ap.parse_args(argv)

    from dataclasses import replace

    from erosion.mass import collect_sources, compute
    from erosion.mass_baseline import (
        baseline_from,
        laundered_metrics,
        load_mass_baseline,
        refresh_entries,
        save_mass_baseline,
        write_mass_baseline,
    )

    finding = compute(collect_sources(args.src))
    comment = _COMMENT.format(reason=args.reason)

    if not args.only:
        save_mass_baseline(args.out, finding, comment=comment)
        print(
            f"wrote {args.out}: {len(finding.god_files)} god file(s), "
            f"{len(finding.god_classes)} god class(es) over {finding.total_files} sources"
        )
        return 0

    baseline = load_mass_baseline(args.out)

    # Refuse to RAISE a mark that was not the point of this refresh. `--only`
    # isolates entries from each other; it cannot isolate the metrics within
    # one, and both numbers sit on adjacent lines so the rise is invisible in
    # review (#12142).
    grown = laundered_metrics(baseline, baseline_from(finding), args.only)
    if grown and not args.allow_metric_growth:
        print(
            "error: this refresh lowers one metric and raises another in the "
            "same entry — the raise was not the errand:",
            file=sys.stderr,
        )
        for key, rises in grown.items():
            for metric, (old, new) in rises.items():
                print(
                    f"  {key}  {metric}: {old} -> {new}  (+{new - old})",
                    file=sys.stderr,
                )
        print(
            "\nA class entry holds loc AND methods on adjacent lines, so a "
            "re-record for one carries the other silently (#12142). Either "
            "bring the raised metric back under its mark, or pass "
            "--allow-metric-growth and account for it in --reason.",
            file=sys.stderr,
        )
        return 1

    try:
        refreshed, updated, removed = refresh_entries(baseline, finding, args.only)
    except KeyError as exc:
        print(f"error: {exc.args[0]}", file=sys.stderr)
        return 1

    # dict.fromkeys mirrors refresh_entries' own dedup, so a repeated --only is
    # reported once rather than echoed per occurrence.
    unchanged = [
        k for k in dict.fromkeys(args.only) if k not in updated and k not in removed
    ]
    if not updated and not removed:
        # Nothing moved, so the file does not move either — a "Last moved"
        # comment on an unchanged baseline is exactly the decorative rot this
        # mode exists to stop.
        print(f"{args.out} already matches the live reading; nothing written")
        for key in unchanged:
            print(f"  unchanged {key}")
        return 0

    write_mass_baseline(args.out, replace(refreshed, comment=comment))
    print(f"wrote {args.out}: {len(updated)} updated, {len(removed)} removed")
    for key in updated:
        print(f"  updated   {key}")
    for key in removed:
        print(f"  removed   {key} (no longer over threshold)")
    for key in unchanged:
        print(f"  unchanged {key} (already accurate)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
