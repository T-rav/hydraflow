"""#11902: the deletion gate must fail CLOSED when it cannot compare.

The gate shipped broken, in the same shape it was written to close.

`_git` ran with ``check=False`` and returned stdout. On the CI checkout
``git diff origin/staging...HEAD`` exited non-zero — ``origin/staging`` did not
exist, because ``git fetch --no-tags --depth=200 origin <branch>`` updates
FETCH_HEAD only and does NOT create ``refs/remotes/origin/<branch>`` — so stdout
was empty, and an empty deletion list reads exactly like "this PR deletes
nothing".

Measured, not theorised: pushing a real out-of-scope deletion to the gate's own
PR produced

    [deletion-scope OK] no files deleted

with a green tick, on a commit that deleted
``docs/superpowers/plans/2026-07-24-signal-control-substrate.md``. After the fix
the same commit turned the step red and named the path.

A gate for silent deletions that itself fails silently is worse than no gate: it
occupies the slot a working one would have. These pin the direction of failure,
which is the only property that made it dangerous.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import check_deletion_scope as gate


def test_an_unresolvable_base_fails_rather_than_reporting_no_deletions(
    tmp_path: Path,
) -> None:
    """Returning 0 here is the shipped bug: no comparison was made, and
    'nothing found' was reported as 'nothing there'."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert (
        gate.main(["--base", "origin/definitely-not-a-branch", "--head", "HEAD"]) == 1
    )


def test_a_failing_git_command_raises_instead_of_returning_empty() -> None:
    """The mechanism. Empty stdout from a FAILED command is indistinguishable
    from empty stdout from a successful one, and only one of them means
    'nothing to report'."""
    with pytest.raises(gate.BaseUnresolvable):
        gate._git("rev-parse", "--verify", "definitely-not-a-ref^{commit}")


def test_the_ci_lane_fetches_a_refspec_that_creates_the_remote_ref() -> None:
    """`git fetch origin <branch>` updates FETCH_HEAD only. Without the explicit
    `+refs/heads/X:refs/remotes/origin/X` the base ref never exists, which is
    precisely how the gate went green while blind."""
    workflow = (
        Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
    ).read_text(encoding="utf-8")
    assert "refs/remotes/origin/${{ github.base_ref }}" in workflow, (
        "the deletion-scope lane must fetch an explicit refspec, or "
        "origin/<base> will not exist and the gate cannot see anything"
    )


def test_the_ci_lane_checks_out_enough_history_for_a_merge_base() -> None:
    """`fatal: no merge base`, observed on this PR's own CI.

    ``actions/checkout`` defaults to ``--depth=1`` of the PR MERGE ref. A base
    branch fetched separately then shares no history with it, so
    ``git diff base...HEAD`` cannot resolve a merge base and the step dies.
    Before the gate failed closed this was invisible; after, it was the very
    next thing it reported. Full depth is the only setting that reliably has a
    merge base.
    """
    workflow = (
        Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
    ).read_text(encoding="utf-8")
    lane = workflow[workflow.index("  conflict-markers:") :]
    lane = lane[: lane.index("\n  ", 1) if "\n  " in lane[1:] else len(lane)]
    assert "fetch-depth: 0" in workflow.split("conflict-markers:")[1][:900], (
        "the deletion-scope lane needs full history; at --depth=1 the "
        "three-dot diff has no merge base and the step cannot run at all"
    )
