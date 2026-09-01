#!/usr/bin/env python3
"""Fail when a PR deletes files outside the subtree it is otherwise working in.

**The defect this closes (#11902).** Squashing a branch with
``git reset --soft <newer-ref>`` moves HEAD forward and leaves the working tree
alone; a following ``git add -A`` then diffs the OLD tree against the NEW ref,
so every file the newer ref ADDED is recorded as a DELETION. One such commit
removed 16 files belonging to two already-merged PRs and passed every gate:
ruff, arch-check, the pre-commit hooks, and ``make audit`` at
PASS 94 / WARN 1 / FAIL 0.

Nothing caught it because every other gate asks *"is what is here correct?"*.
A deletion is invisible to a correctness check — the deleted thing is no longer
around to be incorrect, and the tests that covered it were deleted with it.

**Why deletions are not simply banned.** They are routinely legitimate:
decomposing a module into a package deletes the module, and a retirement PR
deletes what it retires. Measured over the last 14 deletion-carrying commits on
``staging``, a bare in-scope rule flags **6 of 14** — every one of them a
deliberate removal. A gate that cries wolf on 42% of real work gets switched
off, and a switched-off gate is worse than the defect it was written for.

**So the rule is narrower than "declare every deletion".** A deletion is
*in scope* — and needs no declaration at all — when the PR is demonstrably
working in that area:

* another file in the SAME directory is added or modified, or
* the deleted module became a package: ``src/foo.py`` deleted while the PR adds
  under ``src/foo/`` (the batch 5-8 decomposition shape).

Only an out-of-scope deletion must be declared, with a ``Removes:`` trailer
that NAMES the path. Naming is the point: the incident deleted 16 files its
author never intended to touch, and no one writes sixteen paths they did not
mean. A removal PR — the 6 legitimate cases above — writes one line about the
thing it exists to remove.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

_TRAILER = re.compile(r"^\s*Removes:\s*(.+)$", re.MULTILINE | re.IGNORECASE)


class BaseUnresolvable(RuntimeError):
    """The base ref is not present, so no honest comparison can be made."""


def _git(*args: str) -> str:
    """Run git, FAILING LOUDLY on a non-zero exit.

    This was ``check=False`` and returned stdout, which is how the first
    version of this gate shipped broken: on a shallow CI checkout
    ``git diff origin/staging...HEAD`` exits non-zero, stdout is empty, and an
    empty deletion list reads exactly like "this PR deletes nothing". The gate
    reported ``[deletion-scope OK] no files deleted`` on a branch that deleted a
    file, and went green.

    A gate for silent deletions that itself fails silently is worse than no
    gate: it occupies the slot a working one would have.
    """
    done = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise BaseUnresolvable(
            f"`git {' '.join(args)}` exited {done.returncode}: "
            f"{done.stderr.strip() or '(no stderr)'}"
        )
    return done.stdout.strip()


def _names(base: str, head: str, diff_filter: str) -> list[str]:
    """Paths in the base..head diff. ``-M`` on purpose: a RENAME is not a
    deletion, and without rename detection every move would be reported here."""
    out = _git(
        "diff", f"{base}...{head}", "-M", f"--diff-filter={diff_filter}", "--name-only"
    )
    return [line for line in out.split("\n") if line]


def declared_paths(text: str) -> list[str]:
    """Every path named by a ``Removes:`` trailer in *text*."""
    found: list[str] = []
    for match in _TRAILER.finditer(text or ""):
        found.extend(p.strip() for p in match.group(1).replace(",", " ").split())
    return [p for p in found if p]


def out_of_scope(deleted: list[str], touched: list[str]) -> list[str]:
    """Deletions the PR shows no other sign of working on."""
    touched_dirs = {path.rpartition("/")[0] for path in touched}
    offenders: list[str] = []
    for path in deleted:
        parent = path.rpartition("/")[0]
        if parent in touched_dirs:
            continue
        # `src/foo.py` retired into the package `src/foo/` — the decomposition
        # shape this repo runs every few weeks (batches 5-8).
        if path.endswith(".py"):
            package = f"{path[: -len('.py')]}/"
            if any(t.startswith(package) for t in touched):
                continue
        offenders.append(path)
    return offenders


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="origin/staging")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument(
        "--declaration",
        default="",
        help="extra text scanned for Removes: trailers (e.g. the PR body)",
    )
    args = ap.parse_args(argv)

    # Resolve the base BEFORE diffing. A missing ref is the shallow-checkout
    # case, and it must be loud: silently comparing against nothing is how this
    # gate first shipped green while a file was being deleted.
    try:
        _git("rev-parse", "--verify", "--quiet", f"{args.base}^{{commit}}")
    except BaseUnresolvable:
        print(
            f"[deletion-scope FAILED] base ref {args.base!r} is not present in "
            "this checkout, so no deletion comparison is possible. On a shallow "
            "CI clone, fetch it explicitly:\n"
            f"    git fetch --no-tags origin "
            f"+refs/heads/{args.base.removeprefix('origin/')}:"
            f"refs/remotes/origin/{args.base.removeprefix('origin/')}",
            file=sys.stderr,
        )
        return 1

    deleted = _names(args.base, args.head, "D")
    if not deleted:
        print("[deletion-scope OK] no files deleted")
        return 0

    touched = _names(args.base, args.head, "AM")
    offenders = out_of_scope(deleted, touched)
    if not offenders:
        print(
            f"[deletion-scope OK] {len(deleted)} deletion(s), all in a subtree "
            "this branch is otherwise working in"
        )
        return 0

    commits = _git("log", f"{args.base}..{args.head}", "--format=%B")
    declared = declared_paths(f"{commits}\n{args.declaration}")
    undeclared = [p for p in offenders if p not in declared]
    if not undeclared:
        print(
            f"[deletion-scope OK] {len(offenders)} out-of-scope deletion(s), "
            "each named by a Removes: trailer"
        )
        return 0

    print(
        f"[deletion-scope FAILED] {len(undeclared)} file(s) deleted outside any "
        f"subtree this branch otherwise touches, and not declared:\n"
        + "\n".join(f"  {p}" for p in undeclared)
        + "\n\nIf the removal is intended, name each path in a `Removes:` "
        "trailer on any commit in this branch:\n"
        f"    Removes: {undeclared[0]}\n\n"
        "If it is NOT intended, this is the #11902 shape: `git reset --soft` "
        "onto a NEWER ref followed by `git add -A` records every file that ref "
        "added as a deletion. Check `git diff "
        f"{args.base}...{args.head} --diff-filter=D --name-only` against what "
        "you meant to change.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
