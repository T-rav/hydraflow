"""Boot-correctness guard for the Tier-1 liveness kernel (#10734).

The honest-restart rule: the kernel must NEVER ``POST /api/control/start`` onto
a factory whose running bytecode does not match ``origin/<factory_branch>`` HEAD.
On 2026-07-27 a restart booted the factory **90 commits behind on ``main``,
idle** — a "successful restart" into a stale, wrong-branch state. This module is
the deterministic guard that prevents that *at launch* instead of detecting it
after the fact.

Two halves, mirroring ``scripts/gates/``:

* a PURE decision core (:func:`decide_boot_action`) — a truth table over the
  workspace branch, the ``origin/<branch>`` tip, and the factory's reported
  ``boot_sha`` / ``commits_behind`` / ``status``. No I/O; fully unit-testable.
* a thin I/O edge (git probes + a ``GET /api/control/status`` read) that gathers
  those facts, each subprocess/HTTP call bounded and failure-tolerant.

**Fail-closed:** an unknown fact never authorises START; only a *definite*
mismatch triggers RESYNC_REBOOT. An unreadable remote can therefore never spin
the kernel into a reboot loop — it degrades to NO_ACTION plus a notify.

**Operator Stop is a latch (ADR-0135):** ``/api/control/status`` also carries
``operator_stopped`` — the persisted ``POST /api/control/stop`` intent that
``src/factory_autostart.py`` already honours. A verified-correct *idle* boot
under that latch is NO_ACTION, never START, so the kernel cannot undo a
deliberate Stop on its next tick. The field is read fail-open (missing → False).

Stdlib only — this is the error kernel; it must not import ``src/`` (the thing
it watches) or it cannot run when that thing is broken.
"""

from __future__ import annotations

import enum
import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# Bounded so a wedged git process or stalled remote can never hang the kernel.
GIT_TIMEOUT_SECONDS = 20.0
FETCH_TIMEOUT_SECONDS = 30.0
STATUS_TIMEOUT_SECONDS = 5.0


class BootAction(enum.StrEnum):
    """What the boot guard authorises this tick."""

    #: Boot verified correct AND the host line is idle → kick it with start.
    START = "start"
    #: A definite staleness / wrong-branch signal → force-sync + relaunch.
    RESYNC_REBOOT = "resync_reboot"
    #: Boot correct + already running, OR facts unknown (fail-closed). Do nothing.
    NO_ACTION = "no_action"


@dataclass(frozen=True)
class BootDecision:
    """The boot guard's verdict for one tick — computed with no side effects."""

    action: BootAction
    reason: str
    notify: bool = False


# Reported statuses where the host orchestrator line is not actively running, so
# a boot verified correct may be kicked with ``POST /api/control/start``.
STARTABLE_STATUSES = frozenset({"idle", "done"})


def _definite_mismatch_reason(
    *,
    workspace_branch: str | None,
    factory_branch: str,
    origin_head: str | None,
    boot_sha: str | None,
    commits_behind: int | None,
) -> str | None:
    """The reason a boot is *definitely* stale/wrong-branch, or None if not.

    Only definite signals count (an unknown fact is never a mismatch — that is
    the fail-closed contract): a workspace on the wrong branch, a non-zero
    commits-behind (independent of a readable boot_sha), or a boot_sha that
    differs from a *known* origin tip.
    """
    if workspace_branch is not None and workspace_branch != factory_branch:
        return (
            f"workspace on {workspace_branch!r}, factory branch is {factory_branch!r}"
        )
    if commits_behind is not None and commits_behind > 0:
        return f"boot is {commits_behind} commits behind origin/{factory_branch}"
    if boot_sha is not None and origin_head is not None and boot_sha != origin_head:
        return f"boot_sha {boot_sha[:12]} != origin/{factory_branch} {origin_head[:12]}"
    return None


def decide_boot_action(
    *,
    workspace_branch: str | None,
    factory_branch: str,
    origin_head: str | None,
    boot_sha: str | None,
    commits_behind: int | None,
    status: str | None,
    operator_stopped: bool = False,
) -> BootDecision:
    """Pure core: decide START / RESYNC_REBOOT / NO_ACTION from this tick's facts.

    START is returned *only* when every fact is affirmatively correct: the
    workspace is on ``factory_branch``, the reported ``boot_sha`` equals the
    ``origin/<branch>`` tip, ``commits_behind`` is exactly ``0``, the host
    line is idle, AND the operator has not latched it stopped. Any *definite*
    mismatch (wrong branch, non-zero commits-behind, or a boot_sha that differs
    from a known origin tip) returns RESYNC_REBOOT. Everything else — unknown
    git facts, an unreadable status, or a correct boot that is already running
    — returns NO_ACTION.

    ``operator_stopped`` is the persisted ``POST /api/control/stop`` latch
    (ADR-0135): after a Stop the status API reads ``idle`` — exactly like a
    never-started boot — so without it a verified-correct boot would be kicked
    straight back up on the next tick. The latch suppresses START only; a stale
    boot is still healed (RESYNC_REBOOT) and relaunches INTO the latch, where
    ``src/factory_autostart.py`` keeps it stopped. Defaults False so a factory
    that predates the field keeps the prior behaviour (fail-open).
    """
    if status is None:
        # Status API unreadable: we cannot judge boot correctness at all. The
        # down-detection path (healthz/events) owns the unreachable case; here
        # we simply decline to act — never reboot a factory we cannot see.
        return BootDecision(BootAction.NO_ACTION, "status-unreadable")

    # --- Definite mismatch -> resync + reboot (evaluated before START gating) ---
    mismatch = _definite_mismatch_reason(
        workspace_branch=workspace_branch,
        factory_branch=factory_branch,
        origin_head=origin_head,
        boot_sha=boot_sha,
        commits_behind=commits_behind,
    )
    if mismatch is not None:
        return BootDecision(BootAction.RESYNC_REBOOT, mismatch, notify=True)

    # --- No definite mismatch. START only if EVERY fact is affirmatively correct. ---
    boot_correct = (
        workspace_branch == factory_branch
        and origin_head is not None
        and boot_sha is not None
        and boot_sha == origin_head
        and commits_behind == 0
    )
    if not boot_correct:
        # Fail-closed: at least one fact is unknown (e.g. the origin tip is
        # unavailable). Never START on an unverified boot; never reboot on a
        # mere unknown — that would risk a 5-minute reboot loop.
        return BootDecision(
            BootAction.NO_ACTION,
            "boot correctness unverified (unknown git facts)",
            notify=True,
        )

    if status in STARTABLE_STATUSES:
        if operator_stopped:
            # A deliberate Stop is not an incident: no start, no notification.
            return BootDecision(
                BootAction.NO_ACTION, "operator stopped the factory — not starting"
            )
        return BootDecision(BootAction.START, f"boot verified correct, status={status}")
    # running / stopping / credits_paused / auth_failed on a correct boot: the
    # factory is already alive on the right code — never redundantly start it.
    return BootDecision(
        BootAction.NO_ACTION, f"boot correct, status={status} (already active)"
    )


# --------------------------------------------------------------------------
# I/O edge — bounded, failure-tolerant git + HTTP probes. Everything below
# returns ``None`` rather than raising, so the kernel can never hang or crash.
# --------------------------------------------------------------------------


def _run_git(workspace: Path, args: list[str], *, timeout: float) -> str | None:
    """Run a read-only git command in ``workspace``; stripped stdout or None."""
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-C", str(workspace), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    return out or None


def git_current_branch(workspace: Path) -> str | None:
    """The branch ``workspace`` HEAD is on, or None (detached / unreadable)."""
    branch = _run_git(
        workspace, ["rev-parse", "--abbrev-ref", "HEAD"], timeout=GIT_TIMEOUT_SECONDS
    )
    if branch is None or branch == "HEAD":  # "HEAD" => detached; treat as unknown.
        return None
    return branch


def git_origin_head(workspace: Path, branch: str) -> str | None:
    """SHA of ``origin/<branch>`` after a bounded ``fetch --prune``, or None.

    The fetch refreshes the remote-tracking ref so commits-behind is measured
    against the true remote tip; its failure (offline host) is ignored — we then
    resolve whatever local ``origin/<branch>`` we already have, and a fully
    unavailable ref returns None (fail-closed at the decision layer).
    """
    _run_git(workspace, ["fetch", "origin", "--prune"], timeout=FETCH_TIMEOUT_SECONDS)
    return _run_git(
        workspace, ["rev-parse", f"origin/{branch}"], timeout=GIT_TIMEOUT_SECONDS
    )


def fetch_control_status(
    url: str, *, timeout: float = STATUS_TIMEOUT_SECONDS
) -> dict | None:
    """GET ``/api/control/status`` and return the parsed body, or None.

    Best-effort and bounded: any non-http(s) scheme, connection error, timeout,
    non-2xx/3xx status, or unparseable body yields None.
    """
    # Reject non-http(s) before urlopen ever runs (bandit B310 honours file://).
    if urllib.parse.urlparse(url).scheme not in {"http", "https"}:
        return None
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # nosec B310
            if not (200 <= resp.status < 400):
                return None
            body = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def extract_status_fields(
    status_json: dict,
) -> tuple[str | None, str | None, int | None, bool]:
    """Pure: pull ``(status, boot_sha, commits_behind, operator_stopped)``.

    ``boot_sha`` / ``commits_behind`` live under the nested ``config`` object
    (``ControlStatusConfig``); any missing or wrong-typed field becomes None.
    ``operator_stopped`` is the top-level latch (``ControlStatusResponse``,
    ADR-0135): only a literal JSON ``true`` counts — missing or any other type
    fails open to ``False`` so an older factory keeps the prior START path.
    """
    raw_status = status_json.get("status")
    status = raw_status if isinstance(raw_status, str) else None
    operator_stopped = status_json.get("operator_stopped") is True

    boot_sha: str | None = None
    commits_behind: int | None = None
    config = status_json.get("config")
    if isinstance(config, dict):
        raw_sha = config.get("boot_sha")
        boot_sha = raw_sha if isinstance(raw_sha, str) else None
        raw_behind = config.get("commits_behind")
        # bool is an int subclass — exclude it so a stray True/False is not read
        # as 1/0 commits behind.
        if isinstance(raw_behind, int) and not isinstance(raw_behind, bool):
            commits_behind = raw_behind
    return status, boot_sha, commits_behind, operator_stopped


def probe_boot_correctness(
    *, workspace: Path, factory_branch: str, status_url: str
) -> BootDecision:
    """Gather live facts and return the boot decision. Never raises.

    Reads the factory's ``/api/control/status`` (the authoritative boot_sha /
    commits_behind / status) and probes the isolated workspace's git branch +
    ``origin/<branch>`` tip, then feeds them all to :func:`decide_boot_action`.
    """
    status_json = fetch_control_status(status_url)
    if status_json is None:
        return BootDecision(BootAction.NO_ACTION, "status-unreadable")
    status, boot_sha, commits_behind, operator_stopped = extract_status_fields(
        status_json
    )
    return decide_boot_action(
        workspace_branch=git_current_branch(workspace),
        factory_branch=factory_branch,
        origin_head=git_origin_head(workspace, factory_branch),
        boot_sha=boot_sha,
        commits_behind=commits_behind,
        status=status,
        operator_stopped=operator_stopped,
    )
