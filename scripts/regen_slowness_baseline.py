#!/usr/bin/env python3
"""Regenerate the suite-time set-point — a deliberate, reviewed act.

    make test                                  # produces the measurement
    python scripts/regen_slowness_baseline.py --reason "why the mark moved"

The ratchet (``tests/architecture/test_slowness_ratchet.py``) fails when the
slow-test SHARE rises past the recorded mark plus its tolerance. Rerun this
after genuinely making the suite faster so the lower mark locks in — never to
turn a red ratchet green without deciding.

It refuses to record an unmeasured or trivially small reading. A set-point
taken from a run that measured 12 tests would be a number with no relationship
to the suite, and every later comparison against it would be noise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_BASELINE = Path("disturbance/baselines/slowness.yaml")
_DURATIONS = Path(".hydraflow/test_durations.json")
#: Below this the reading is a lane, not the suite, and must not become a mark.
_MIN_MEASURED_TESTS = 500


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reason", required=True, help="why the mark is being moved")
    ap.add_argument("--durations", type=Path, default=_DURATIONS)
    ap.add_argument("--out", type=Path, default=_BASELINE)
    ap.add_argument("--tolerance", type=float, default=None)
    args = ap.parse_args(argv)

    from erosion.slowness import collect_durations, compute
    from erosion.slowness_baseline import (
        DEFAULT_TOLERANCE,
        load_slowness_baseline,
        save_slowness_baseline,
    )

    durations = collect_durations(args.durations)
    if not durations:
        print(
            f"no measurement at {args.durations} — run `make test` first "
            "(it sets HYDRAFLOW_DURATIONS_OUT). Refusing to record an empty "
            "reading as a set-point.",
            file=sys.stderr,
        )
        return 1
    if len(durations) < _MIN_MEASURED_TESTS:
        print(
            f"only {len(durations)} tests measured (need >= {_MIN_MEASURED_TESTS}). "
            "That is a lane, not the suite; a mark taken from it would make every "
            "later comparison noise. Run the full `make test`.",
            file=sys.stderr,
        )
        return 1

    finding = compute(durations)
    tolerance = (
        args.tolerance
        if args.tolerance is not None
        else load_slowness_baseline(args.out).tolerance or DEFAULT_TOLERANCE
    )
    save_slowness_baseline(args.out, finding, comment=args.reason, tolerance=tolerance)
    print(
        f"wrote {args.out}: {len(finding.slow_tests)} test(s) over "
        f"{finding.threshold_seconds:.0f}s holding {finding.share:.1%} of "
        f"{finding.total_seconds:.0f}s across {finding.total_tests} measured tests"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
