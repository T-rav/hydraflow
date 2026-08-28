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

Two detectors, because the lane has two instruments:

* :attr:`ReachDetector.HOOK` — the audit hook sees the reach in this process.
  Re-checked by observing it: at least one violation must still be recorded.
* :attr:`ReachDetector.NAMESPACE` — the reach happens inside a CHILD process
  (``mkdocs`` asking ``unpkg.com`` whether the mermaid bundle exists), where no
  audit hook of ours runs and the kernel is the only witness. Re-checked the
  only way it can be: the file must still FAIL with egress blocked. A pass
  means the reach is gone and so is the exclusion.

Pointing the wrong detector at an entry answers "no reach observed" and reports
a live exclusion as stale, which is this check lying in the direction that
reopens a hole. So the detector is registered, not guessed.

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
    EgressLaneExclusion,
    ReachDetector,
)

_RETIRE = (
    "DELETE the entry and lower EGRESS_LANE_EXCLUSION_CEILING — the lane can "
    "cover this file now, and an exclusion that outlives its reason "
    "pre-approves whatever lands in that file next."
)


def _recheck(exclusion: EgressLaneExclusion) -> list[str]:
    """Is this exclusion still necessary? Complaints, or an empty list."""
    with tempfile.TemporaryDirectory() as scratch:
        result = run_under_guard(
            [exclusion.path],
            repo_root=_REPO,
            report_dir=Path(scratch),
            block=False,
        )

    if result.tests_run == 0:
        return [
            f"{exclusion.path}: collected no tests, so nothing was observed. "
            "That is inconclusive, not clean."
        ]

    if exclusion.detected_by is ReachDetector.HOOK:
        observed = [violation.describe() for violation in result.violations]
        print(f"{exclusion.path} [hook]: {len(observed)} reach(es) observed")
        for line in observed:
            print(f"    {line}")
        if observed:
            return []
        return [
            f"{exclusion.path}: reaches nothing any more (registered as "
            f"{list(exclusion.reaches)}). {_RETIRE}"
        ]

    # NAMESPACE: the reach is in a child process, so the only evidence
    # available here is that blocking egress still breaks the file.
    verdict = "FAILED (still needs egress)" if result.returncode else "PASSED"
    print(f"{exclusion.path} [namespace]: {verdict} with egress blocked")
    if result.returncode:
        return []
    return [
        f"{exclusion.path}: PASSES with egress blocked, so it no longer needs "
        f"the network (registered as {list(exclusion.reaches)}). {_RETIRE}"
    ]


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
        stale.extend(_recheck(exclusion))

    if stale:
        print("\n".join(("", "STALE EGRESS-LANE EXCLUSIONS:", *stale)), file=sys.stderr)
        return 1

    print(f"check_egress_exclusions: {len(EGRESS_LANE_EXCLUSIONS)} exclusion(s) live.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
