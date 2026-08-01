#!/usr/bin/env python3
"""Regenerate the concentration (god-file) baseline — a deliberate, reviewed act.

The ratchet guard (``tests/architecture/test_concentration_ratchet.py``) fails
when a NEW god-file appears beyond the committed baseline. Rerun this ONLY when
that new concentration point is an accepted architectural decision — the whole
point is that adopting a new god-file is a conscious choice, not a silent drift.

    python scripts/regen_concentration_baseline.py --reason "why the new god-file is accepted"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from erosion.concentration import compute, extract_file_import_graph  # noqa: E402
from erosion.concentration_baseline import save_concentration_baseline  # noqa: E402

_BASELINE = Path("disturbance/baselines/concentration.yaml")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reason", required=True, help="why the baseline is being moved")
    ap.add_argument("--src", type=Path, default=Path("src"))
    ap.add_argument("--out", type=Path, default=_BASELINE)
    args = ap.parse_args(argv)

    finding = compute(extract_file_import_graph(args.src))
    save_concentration_baseline(
        args.out,
        finding,
        comment=(
            "Grandfathered god-files (file-level fan-in >= threshold) — the "
            "concentration counter-metric to erosion.spread (#10840). The gate "
            f"flags NEW god-files beyond this set. Last moved: {args.reason}"
        ),
    )
    print(
        f"Wrote {args.out}: {len(finding.god_modules)} god-files, "
        f"max fan-in {finding.max_fan_in}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
