#!/usr/bin/env python3
"""Every egress-lane exclusion must still reach the network (#11706).

``EGRESS_LANE_EXCLUSIONS`` names the conformance files the egress-blocked lane
does not run, because they really do leave the checkout. That list is the one
place in this design where "someone wrote it down" is still load-bearing, and a
written-down exemption rots the same way every other one in this repo did: the
file gets fixed, the entry stays, and it silently pre-approves whatever lands
in that path next.

So the entry is checked against the thing it claims. Each excluded file is run
with :mod:`tests.architecture.egress_guard` armed in OBSERVE mode, and must
still produce at least one reach. If it does not, the exclusion is over and the
answer is to delete it — not to leave it covering a file the lane could have
been covering all along.

Run it INSIDE the lane. ``scripts/offline_egress_lane.sh`` exports
``HF_EGRESS_ISOLATED=1`` once its canaries pass, and this script refuses to run
without it: outside a namespace, "observe the reach" means *perform* the reach,
against a real forge, from CI. Inside one, the ``connect``/``Popen`` audit event
still fires and the syscall behind it still fails, which is exactly the
observation wanted and none of the traffic.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "src"))

from tests.architecture.egress_guard import run_under_guard  # noqa: E402
from tests.architecture.vitals_conformance_registry import (  # noqa: E402
    EGRESS_LANE_EXCLUSIONS,
)


def main() -> int:
    if os.environ.get("HF_EGRESS_ISOLATED") != "1":
        print(
            "check_egress_exclusions: refusing to run outside the lane. These "
            "files reach a real forge; observing them without a network "
            "namespace around the process would make the check the thing it is "
            "checking for. Run it via scripts/offline_egress_lane.sh.",
            file=sys.stderr,
        )
        return 2

    if not EGRESS_LANE_EXCLUSIONS:
        print("check_egress_exclusions: no exclusions registered — nothing to do.")
        return 0

    stale: list[str] = []
    for exclusion in EGRESS_LANE_EXCLUSIONS:
        with tempfile.TemporaryDirectory() as scratch:
            result = run_under_guard(
                [exclusion.path],
                repo_root=_REPO,
                report_dir=Path(scratch),
                block=False,
            )
        observed = [violation.describe() for violation in result.violations]
        print(f"{exclusion.path}: {len(observed)} reach(es) observed")
        for line in observed:
            print(f"    {line}")
        if result.tests_run == 0:
            stale.append(
                f"{exclusion.path}: collected no tests, so nothing was observed. "
                "That is inconclusive, not clean."
            )
        elif not observed:
            stale.append(
                f"{exclusion.path}: reaches nothing any more (registered as "
                f"{list(exclusion.reaches)}). DELETE the entry and lower "
                "EGRESS_LANE_EXCLUSION_CEILING — the lane can cover this file "
                "now, and an exclusion that outlives its reason pre-approves "
                "whatever lands in that file next."
            )

    if stale:
        print("\n".join(("", "STALE EGRESS-LANE EXCLUSIONS:", *stale)), file=sys.stderr)
        return 1

    print(f"check_egress_exclusions: {len(EGRESS_LANE_EXCLUSIONS)} exclusion(s) live.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
