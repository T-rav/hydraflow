#!/usr/bin/env python3
"""Regenerate the mass (god-file / god-class size) baseline — a deliberate, reviewed act.

The ratchet guard (``tests/architecture/test_mass_ratchet.py``) fails when a NEW
god file or god class appears beyond the committed baseline. Rerun this when a
decomposition landed (so the smaller size is recorded and the next growth is
caught) or when a new oversized class is an accepted decision — never to make
a red ratchet green without deciding.

    python scripts/regen_mass_baseline.py --reason "decomposed PRManager promotion cluster"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_BASELINE = Path("disturbance/baselines/mass.yaml")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reason", required=True, help="why the baseline is being moved")
    ap.add_argument("--src", type=Path, default=Path("src"))
    ap.add_argument("--out", type=Path, default=_BASELINE)
    args = ap.parse_args(argv)

    from erosion.mass import collect_sources, compute
    from erosion.mass_baseline import save_mass_baseline

    finding = compute(collect_sources(args.src))
    save_mass_baseline(
        args.out,
        finding,
        comment=(
            "Grandfathered god files (LOC >= file threshold) and god classes "
            "(LOC or method count >= class thresholds) — the mass sensor "
            "(erosion.mass). The gate flags NEW entries beyond this set; the "
            f"ErosionMetricsLoop files the burn-down roster. Last moved: {args.reason}"
        ),
    )
    print(
        f"wrote {args.out}: {len(finding.god_files)} god file(s), "
        f"{len(finding.god_classes)} god class(es) over {finding.total_files} sources"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
