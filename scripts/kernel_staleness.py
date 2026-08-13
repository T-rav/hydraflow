#!/usr/bin/env python3
"""Kernel staleness report — is a stamped child current with the building code?

Slice 1 of #11060 (read side). Loads the child's ``hydraflow-kernel.lock``,
recomputes the CURRENT prescription for the same spec from the running
HydraFlow checkout, and classifies every locked file:

* ``KERNEL_UPDATED``   — the building code moved on (the update-PR worklist);
* ``LOCALLY_MODIFIED`` — the child diverged (surfaced, never auto-overwritten);
* ``MISSING`` / ``CURRENT``.

Exit codes: 0 fully current · 1 stale (version or files) · 2 no lock (a
pre-#11060 stamp — re-stamp to adopt the manifest).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from onboarding.kernel_lock import (  # noqa: E402
    compare,
    load_lock,
    render_staleness,
)
from onboarding.kernel_writer import prescription, spec_from_lock  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report a stamped child's freshness against the building code."
    )
    parser.add_argument("target", help="Stamped repo root to check.")
    args = parser.parse_args()

    child_root = Path(args.target).expanduser().resolve()
    lock = load_lock(child_root)
    if lock is None:
        print(
            f"no {child_root / 'hydraflow-kernel.lock'} — pre-#11060 stamp; "
            "re-run `make stamp DIR=...` to adopt the manifest",
            file=sys.stderr,
        )
        return 2

    spec = spec_from_lock(lock)
    report = compare(lock, current_plan=prescription(spec), child_root=child_root)
    print(render_staleness(report), end="")
    stale = report.version_stale or report.stale_files or report.modified_files
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
