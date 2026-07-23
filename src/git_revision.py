"""Git revision helpers for runtime staleness observability.

Exposes the process **boot SHA** (captured once, in-memory, at first access)
and a cheap, failure-tolerant **commits-behind** count relative to the remote
tracking branch.  Consumed by ``GET /api/control/status`` so operators get an
always-on "you are N commits behind" indicator without waiting for the
StaleCodeWatcher HITL threshold to trip.

Design notes:

* ``get_app_version()`` reports the installed *package* version, which is
  unchanged across commits in a ``pip install -e .`` checkout — useless for
  staleness detection.  The git SHA is the real revision signal.
* The boot SHA is cached the first time it is read and never re-read: a
  ``git pull`` without a process restart advances ``HEAD`` while the running
  bytecode stays stale, so re-reading ``HEAD`` each call would silently mask
  that drift.
* All git reads are local (no network fetch), bounded by a short timeout, and
  failure-tolerant — they return ``None`` rather than raising or hanging, so
  the status endpoint can never wedge on a broken git process.
"""

from __future__ import annotations

import subprocess
from typing import cast

# Short timeout: these are all local, read-only git operations (no network).
# Bounded so the status endpoint can never hang on a wedged git process.
_GIT_TIMEOUT_SECS = 5
# The staging branch is the promotion target the running factory tracks
# (ADR-0042); commits-behind is measured against its remote-tracking ref.
_DEFAULT_BASE_REF = "origin/staging"

# Sentinel distinguishing "not yet captured" from "captured, unavailable".
_UNSET: object = object()
# Single-slot mutable container so the cache can be rebound without `global`
# (PLW0603). Index 0 holds the captured boot SHA (``str`` or ``None`` once
# captured, ``_UNSET`` before first read).
_BOOT_SHA_SLOT: list[object | str | None] = [_UNSET]


def _run_git(args: list[str]) -> str | None:
    """Run a read-only git command, returning stripped stdout or ``None``.

    Failure-tolerant: git missing, non-zero exit, timeout, or "not a repo" all
    return ``None`` rather than raising, so callers never hang or crash.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    return out or None


def get_boot_sha() -> str | None:
    """Return the git ``HEAD`` SHA captured once, in-memory, at first access.

    The value is cached on first read and never re-read (see module docstring).
    Returns ``None`` if the SHA is unavailable.
    """
    if _BOOT_SHA_SLOT[0] is _UNSET:
        _BOOT_SHA_SLOT[0] = _run_git(["rev-parse", "HEAD"])
    # After the sentinel check the slot holds a captured ``str | None``; the
    # ``_UNSET`` sentinel is typed ``object`` (indistinct from the union's
    # ``object`` member) so identity narrowing can't exclude it — cast instead
    # of a blanket ``type: ignore`` (which the suppressions ratchet forbids).
    return cast("str | None", _BOOT_SHA_SLOT[0])


def get_commits_behind(base_ref: str = _DEFAULT_BASE_REF) -> int | None:
    """Return how many commits the boot SHA is behind ``base_ref``.

    Compares the in-memory boot SHA against the *local* remote-tracking ref
    (no network fetch) via ``git rev-list --count <boot_sha>..<base_ref>``.
    Cheap and failure-tolerant: returns ``None`` on any error or if the boot
    SHA / base ref is unavailable.
    """
    boot = get_boot_sha()
    if boot is None:
        return None
    out = _run_git(["rev-list", "--count", f"{boot}..{base_ref}"])
    if out is None:
        return None
    try:
        return int(out)
    except ValueError:
        return None
