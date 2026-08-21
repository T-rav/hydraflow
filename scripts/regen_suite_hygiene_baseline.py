#!/usr/bin/env python3
"""Regenerate the suite-hygiene high-water marks — a deliberate, reviewed act.

The ratchet guard (``tests/architecture/test_suite_hygiene_ratchet.py``) fails
when the count of parametrize copies or cross-file duplicate tests rises ABOVE
the committed marks. Rerun this after a pruning pass so the lower marks lock
in — never to make a red ratchet green without deciding.

    python scripts/regen_suite_hygiene_baseline.py --reason "collapsed test_release groups"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_BASELINE = Path("disturbance/baselines/suite_hygiene.yaml")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reason", required=True, help="why the marks are being moved")
    ap.add_argument("--tests", type=Path, default=Path("tests"))
    ap.add_argument("--out", type=Path, default=_BASELINE)
    args = ap.parse_args(argv)

    from erosion.suite_hygiene import collect_tests, compute
    from erosion.suite_hygiene_baseline import save_suite_hygiene_baseline

    finding = compute(collect_tests(args.tests))
    save_suite_hygiene_baseline(
        args.out,
        finding,
        comment=(
            "High-water marks for structural test redundancy (erosion.suite_hygiene): "
            "parametrize copies (identical bodies in one file) and cross-file duplicate "
            "tests. The gate fails only when a count rises above its mark; falling is "
            f"the point. Last moved: {args.reason}"
        ),
    )
    print(
        f"wrote {args.out}: {finding.total_tests} tests in {finding.total_files} files, "
        f"{finding.parametrize_copies} parametrize copies in "
        f"{len(finding.parametrize_groups)} groups, "
        f"{len(finding.cross_file_duplicates)} cross-file duplicates"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
