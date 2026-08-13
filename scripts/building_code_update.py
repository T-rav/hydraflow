#!/usr/bin/env python3
"""Building-code updater — turn a stale child into a reviewable PR branch (#11060 slice 4).

The "Renovate for the building code", right-sized per the #11055 precedent:
the building-code version is calendar-versioned and changes only when the
kernel itself changes, so a background loop polling a constant would be waste
plus the full new-loop ratchet cost. This is the ON-DEMAND updater; the
caretaker-loop automation joins slice 5's engagement trigger (multiple
registered children + regular bumps).

Flow, per child repo:

1. Read ``hydraflow-kernel.lock`` (exit 2 if absent — run ``make adopt`` /
   ``make stamp`` first; a child without a lock has no update contract).
2. Staleness compare (slice-1 machinery). Fully current → exit 0, no writes.
3. Stale → refuse a dirty working tree, create ``building-code/<version>``
   branch, re-stamp with ``force=True`` (template-owned files only — the
   ownership model protects product files even under force), commit.
4. Print the PR command (printed, not automated — cross-repo GitHub state is
   a deliberate operator action, the same discipline as the stamp's residual
   steps). Exit 1 = update branch created, review pending.

LOCALLY_MODIFIED template files are OVERWRITTEN on the update branch — by
design (slice-1 ruling: KERNEL_UPDATED beats LOCALLY_MODIFIED; "the update
path owns that merge conversation"). The overwrite arrives as a reviewable PR
diff, never silently in the working tree; the operator keeps the local side
by rejecting that hunk in review.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from onboarding.kernel_lock import (  # noqa: E402
    compare,
    load_lock,
    render_staleness,
)
from onboarding.kernel_writer import (  # noqa: E402
    prescription,
    spec_from_lock,
    stamp_kernel,
)

_GIT_TIMEOUT = 30


def _git(child: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=child,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
        check=False,
    )


def working_tree_dirty(child: Path) -> bool:
    result = _git(child, "status", "--porcelain")
    return bool(result.stdout.strip()) or result.returncode != 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update a stamped child to the current building code (#11060)."
    )
    parser.add_argument("target", help="Stamped child repo root.")
    parser.add_argument(
        "--branch-prefix",
        default="building-code",
        help="Update branch name prefix (default: building-code).",
    )
    args = parser.parse_args()

    child = Path(args.target).expanduser().resolve()
    lock = load_lock(child)
    if lock is None:
        print(
            f"no hydraflow-kernel.lock in {child} — run `make adopt DIR={child}` "
            f"then `make stamp DIR={child}` first; a child without a lock has "
            "no update contract",
            file=sys.stderr,
        )
        return 2

    spec = spec_from_lock(lock)
    report = compare(lock, current_plan=prescription(spec), child_root=child)
    print(render_staleness(report), end="")

    stale = report.version_stale or report.stale_files
    if not stale:
        print("current — nothing to update")
        return 0

    return _create_update_branch(
        child, spec, report.current_version, branch_prefix=args.branch_prefix
    )


def _create_update_branch(child, spec, version, *, branch_prefix) -> int:
    """Branch → force re-stamp (template-owned only) → commit → print PR steps."""
    if not (child / ".git").exists():
        print(f"{child} is not a git repo — cannot branch the update", file=sys.stderr)
        return 2
    if working_tree_dirty(child):
        print(
            f"{child} working tree is dirty — commit or stash before updating "
            "(the update must be the only change on its branch)",
            file=sys.stderr,
        )
        return 2

    branch = f"{branch_prefix}/{version}"
    created = _git(child, "checkout", "-b", branch)
    if created.returncode != 0:
        print(
            f"could not create branch {branch}: {created.stderr.strip()}",
            file=sys.stderr,
        )
        return 2

    result = stamp_kernel(spec, child, force=True)
    rewritten = [f.path for f in result.files if f.action in ("written", "rewritten")]
    if not rewritten:
        print("no file changes after re-stamp — lock refreshed only")
    _git(child, "add", "-A")
    commit = _git(
        child,
        "commit",
        "-m",
        f"chore(building-code): update to {version}\n\n"
        f"Re-stamp of template-owned kernel files (product-owned files are\n"
        f"never touched). Files: {len(rewritten)} rewritten. Review any\n"
        f"overwritten local modifications in this diff — keeping the local\n"
        f"side is a review decision, not a silent default.",
    )
    if commit.returncode != 0:
        print(f"commit failed: {commit.stderr.strip()}", file=sys.stderr)
        return 2

    print(f"update branch ready: {branch} ({len(rewritten)} file(s) rewritten)")
    print("next steps (deliberate operator actions):")
    print(f"  cd {child} && git push -u origin {branch}")
    print(
        f"  gh pr create --title 'chore(building-code): update to "
        f"{version}' --body 'Kernel re-stamp; see diff.'"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
