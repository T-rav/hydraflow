#!/usr/bin/env python3
"""Pin the token-drift baseline — a deliberate, reviewed act.

``token_drift.check_drift`` refuses to compare against a missing, too-thin, or
stale baseline (see ``docs/wiki/dark-factory.md`` §4.9 for the full recipe).
Re-pin when the token-efficiency levers this baseline was measured against
have materially changed, or when the existing baseline goes STALE
(older than ``token_drift.MAX_BASELINE_AGE``).

    python scripts/pin_token_baseline.py --reason "..."           # dry-run report
    python scripts/pin_token_baseline.py --reason "..." --apply   # writes the ledger

Telemetry is loaded by WINDOW — every row of the ``--windows`` trailing
complete ISO weeks, however many there are — never by row count (#11581): a
fixed cap silently sampled an 8-week pin from whatever the newest rows
happened to cover. A span the loader knows it cannot cover completely
(``audit_retention_days_inference_telemetry`` shorter than the span, or a
read that died mid-stream) refuses to pin rather than pin a partial week as
if it were whole.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import HydraFlowConfig  # noqa: E402
from token_drift import (  # noqa: E402
    MIN_BASELINE_WINDOWS,
    TokenBaselineLedger,
    iso_week_windows,
    load_window_rows,
    pin_baseline,
    token_baseline_path,
)


def run(config: HydraFlowConfig, *, windows: int, reason: str, apply: bool) -> int:
    now = datetime.now(UTC)
    window = load_window_rows(config, now=now, windows=windows)
    if window.truncated:
        print(
            f"error: telemetry for the trailing {windows} window(s) is incomplete — "
            f"{window.truncation}. Not pinning.",
            file=sys.stderr,
        )
        return 1
    buckets = iso_week_windows(window.rows, now=now, windows=windows)
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
        help=(
            "trailing complete ISO calendar weeks to scan; a week with no "
            f"telemetry yields no window (default: {MIN_BASELINE_WINDOWS})"
        ),
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
