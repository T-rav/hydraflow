#!/usr/bin/env python3
"""CLI for the adopt flow (#11060 slice 3) — brownfield audit, never stamp blind.

Exit codes: 0 safe (a plain stamp only adds NEW files) · 1 review needed
(template-owned files differ — the operator decides which side is right).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from onboarding.adopt import adoption_report, render_adopt  # noqa: E402
from onboarding.kernel_writer import KernelSpec  # noqa: E402


def _default_name(target: Path, pkg: str | None) -> str:
    return pkg or target.name


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit an existing repo against the building code (read-only)."
    )
    parser.add_argument("target", help="Existing repo root to audit.")
    parser.add_argument("--pkg", default=None, help="Import package name.")
    parser.add_argument("--name", default=None, help="Project name.")
    parser.add_argument(
        "--coverage-floor", type=int, default=80, help="Coverage floor (0-100)."
    )
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    spec = KernelSpec(
        name=args.name or _default_name(target, args.pkg),
        package_name=args.pkg,
        coverage_floor=args.coverage_floor,
    )
    report = adoption_report(spec, target)
    print(render_adopt(report, target), end="")
    return 0 if report.safe_to_stamp else 1


if __name__ == "__main__":
    raise SystemExit(main())
