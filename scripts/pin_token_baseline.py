#!/usr/bin/env python3
"""Pin the token-drift baseline — a deliberate, reviewed act.

``token_drift.check_drift`` refuses to compare against a missing, too-thin, or
stale baseline (see ``docs/wiki/dark-factory.md`` §4.9 for the full recipe).
Re-pin when the token-efficiency levers this baseline was measured against
have materially changed, or when the existing baseline goes STALE
(older than ``token_drift.MAX_BASELINE_AGE``).

    python scripts/pin_token_baseline.py --reason "..."           # dry-run report
    python scripts/pin_token_baseline.py --reason "..." --apply   # writes the ledger
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import HydraFlowConfig  # noqa: E402
from prompt_telemetry import PromptTelemetry  # noqa: E402
from token_drift import (  # noqa: E402
    DRIFT_LOAD_LIMIT,
    MIN_BASELINE_WINDOWS,
    TokenBaselineLedger,
    iso_week_windows,
    pin_baseline,
    token_baseline_path,
)


def run(config: HydraFlowConfig, *, windows: int, reason: str, apply: bool) -> int:
    rows = PromptTelemetry(config).load_inferences(limit=DRIFT_LOAD_LIMIT)
    now = datetime.now(UTC)
    buckets = iso_week_windows(rows, now=now, windows=windows)
    if len(buckets) < MIN_BASELINE_WINDOWS:
        print(
            f"error: only {len(buckets)} complete window(s) of telemetry available; "
            f"needs at least {MIN_BASELINE_WINDOWS}. Not pinning.",
            file=sys.stderr,
        )
        return 1

    baseline = pin_baseline(buckets, pinned_at=now)
    print(f"reason:   {reason}")
    print(f"windows:  {baseline.windows_counted} ({buckets[0][0]}..{buckets[-1][0]})")
    print(f"sources:  {sorted(baseline.source_share_series)}")
    print(f"median_tokens_per_issue series: {baseline.median_tokens_series}")

    if not apply:
        print("\nDRY-RUN — rerun with --apply to write the baseline ledger.")
        return 0

    ledger = TokenBaselineLedger(token_baseline_path(config.data_root))
    ledger.record(baseline)
    print(f"\npinned: {ledger.path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reason", required=True, help="why the baseline is being (re)pinned now"
    )
    parser.add_argument(
        "--windows",
        type=int,
        default=MIN_BASELINE_WINDOWS,
        help=f"trailing complete ISO weeks to pin from (default: {MIN_BASELINE_WINDOWS})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the baseline ledger; otherwise prints a dry-run report only",
    )
    args = parser.parse_args(argv)

    config = HydraFlowConfig()
    return run(config, windows=args.windows, reason=args.reason, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
