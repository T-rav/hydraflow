#!/usr/bin/env python3
"""External factory-process liveness watchdog (#10009).

Nothing INSIDE a hung/crashed HydraFlow process can notice that the process
itself is down — that's the whole point of this script. It runs OUTSIDE the
process (via cron or, on macOS, a launchd agent installed by
``scripts/install_liveness_watchdog.py``) on a short interval and checks two
independent signals:

1. ``/healthz`` responds at all (a TCP-connect-and-HTTP-GET, not just a
   "status" field — a "degraded"/"idle" body still means the process is
   ALIVE and responsive; only a connection failure/timeout means it's down).
2. ``events.jsonl``'s last entry isn't stale (catches a process that accepts
   TCP connections but has wedged its event loop and stopped doing work).

On failure it ALWAYS writes/updates a marker file and fires a macOS
notification (best-effort, never fatal if ``osascript`` is unavailable —
e.g. running under cron on a non-macOS box). Automated restart is opt-in: it
only runs if a knob file explicitly enables it, and even then at most ONCE
per continuous down-incident (the "restart-once marker") — no infinite kill
loop if the process can't actually come back up. Default is notify-only.

Deliberately dependency-free and NOT coupled to the ``src/`` HydraFlow
package: a watchdog that imports the thing it's watching can't run when
that thing is broken (missing deps, syntax error from a bad deploy, etc).
Stdlib only.

Tier-1 boot-correctness kernel (#10734): when ``--workspace`` is set (the
production install passes it), the watchdog additionally (a) refuses to start a
factory whose ``boot_sha`` != ``origin/<factory_branch>`` HEAD or that is any
commits behind — force-resyncing + relaunching instead of booting stale; (b)
relaunches pinned to ``staging`` (never the shell default ``main``); (c) reaps
orphaned ``pytest -n auto`` workers from a dead/OOM'd build; and (d) probes a
wedged ``credits_paused_until``. All still stdlib-only and LLM-free.

Usage::

    scripts/factory_liveness_watchdog.py [--dry-run]
        [--healthz-url URL] [--events-path PATH]
        [--stale-seconds N] [--timeout-seconds N]
        [--marker-path PATH] [--knob-path PATH]
        [--workspace DIR] [--factory-branch BRANCH] [--dashboard-port PORT]

Exit code is always 0 on a completed check (success or handled failure) so
cron/launchd never treats a detected outage as "the watchdog itself
crashed"; a genuinely unexpected exception exits 1.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shlex
import signal
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

logger = logging.getLogger("factory_liveness_watchdog")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_MARKER_PATH = Path.home() / ".hydraflow" / "liveness" / "state.json"
_DEFAULT_KNOB_PATH = Path.home() / ".hydraflow" / "liveness" / "restart.knob"
_DEFAULT_HEALTHZ_URL = "http://127.0.0.1:5555/healthz"
_DEFAULT_STALE_SECONDS = 900.0  # 15 min — several ticks of a 5 min watchdog
_DEFAULT_TIMEOUT_SECONDS = 5.0

#: Trailing lines scanned for one parseable event — mirrors
#: src/boot_gap_detector.py's tail-read bound (kept independent on purpose;
#: this script must not import from src/).
_MAX_TAIL_LINES = 200

# --- Tier-1 boot-correctness kernel defaults (#10734) ---
#: Where the isolated factory clone lives (scripts/run-factory-isolated.sh's
#: default workspace). Passing --workspace enables the boot-correctness guard,
#: orphan reaper, and stuck-credit probe; omitting it keeps the legacy
#: notify-only watchdog behaviour (backward compatible).
_DEFAULT_WORKSPACE = Path.home() / ".hydraflow" / "factory-workspace" / "hydraflow"
#: The two-tier model runs the factory on staging (ADR-0042); main advances only
#: via RC promotion. A relaunch must NEVER inherit the shell default of `main`.
_DEFAULT_FACTORY_BRANCH = "staging"
_DEFAULT_DASHBOARD_PORT = 5555
_LAUNCHER_SCRIPT = _REPO_ROOT / "scripts" / "run-factory-isolated.sh"
_HTTP_POST_TIMEOUT_SECONDS = 10.0
_LSOF_TIMEOUT_SECONDS = 5.0


def _load_liveness_modules() -> tuple[ModuleType, ModuleType, ModuleType]:
    """Import the stdlib-only liveness decision cores.

    The import lives in a function (not module top level) so launchd — which
    runs ``python3 scripts/factory_liveness_watchdog.py`` with only ``scripts/``
    on ``sys.path`` — can still resolve the ``scripts.liveness`` package after
    the repo root is inserted, without tripping the E402 "import not at top"
    lint (PLC0415 is repo-ignored). These modules never import ``src/``.
    """
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from scripts.liveness import boot_guard, credit_probe, orphan_reaper

    return boot_guard, credit_probe, orphan_reaper


if TYPE_CHECKING:  # give pyright the real module types for attribute access
    from scripts.liveness import boot_guard, credit_probe, orphan_reaper
else:  # runtime binding via the path-inserting loader above
    boot_guard, credit_probe, orphan_reaper = _load_liveness_modules()


# --------------------------------------------------------------------------
# Pure decision logic — no I/O below this line until `main()`.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    """What this tick should do, computed from inputs with no side effects."""

    is_down: bool
    should_notify: bool
    should_restart: bool
    notify_message: str
    new_marker: dict[str, object] | None  # None means "clear the marker file"


def parse_knob_file(text: str) -> dict[str, str]:
    """Parse a simple ``KEY=VALUE`` knob file (blank lines / ``#`` comments ok).

    Recognised keys: ``RESTART_ENABLED`` (``true``/``false``), ``RESTART_LABEL``
    (a launchd label to ``kickstart``), ``RESTART_COMMAND`` (an arbitrary
    shell command run instead, takes precedence over ``RESTART_LABEL`` when
    both are set).
    """
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def is_restart_enabled(knob: dict[str, str]) -> bool:
    """Pure: does the knob file authorize automated restart?"""
    return knob.get("RESTART_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def decide(
    *,
    healthz_ok: bool,
    events_age_seconds: float | None,
    stale_threshold_seconds: float,
    marker: dict[str, object] | None,
    restart_enabled: bool,
    now: datetime,
) -> Decision:
    """Pure core: given this tick's inputs, decide what to do.

    ``marker`` is the previously-persisted state (``None`` if the factory
    was up last tick / this is the first ever run). Down-ness is
    ``not healthz_ok`` OR the events log being stale by more than
    ``stale_threshold_seconds`` (a wedged-but-still-accepting-TCP process).
    """
    is_down = (not healthz_ok) or (
        events_age_seconds is not None and events_age_seconds > stale_threshold_seconds
    )

    if not is_down:
        if marker is None:
            return Decision(
                is_down=False,
                should_notify=False,
                should_restart=False,
                notify_message="",
                new_marker=None,
            )
        # Recovery: was down last tick, healthy now — clear the marker and
        # send one "recovered" notification so the operator knows it self-
        # healed (or that their manual restart worked).
        down_since = str(marker.get("down_since", "unknown"))
        return Decision(
            is_down=False,
            should_notify=True,
            should_restart=False,
            notify_message=f"HydraFlow factory recovered (was down since {down_since})",
            new_marker=None,
        )

    down_since = str(marker.get("down_since")) if marker else now.isoformat()
    already_restarted = bool(marker.get("restarted")) if marker else False
    should_restart = restart_enabled and not already_restarted

    new_marker: dict[str, object] = {
        "down_since": down_since,
        "last_checked": now.isoformat(),
        "restarted": already_restarted or should_restart,
    }
    notify_message = f"HydraFlow factory appears DOWN since {down_since}"
    if should_restart:
        notify_message += " — attempting automated restart"
    elif restart_enabled and already_restarted:
        notify_message += " — restart already attempted once, not retrying"

    return Decision(
        is_down=True,
        should_notify=True,
        should_restart=should_restart,
        notify_message=notify_message,
        new_marker=new_marker,
    )


# --------------------------------------------------------------------------
# I/O helpers
# --------------------------------------------------------------------------


def read_last_jsonl_timestamp(path: Path) -> datetime | None:
    """Return the timestamp of the last parseable JSONL event, else None."""
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Could not read events log %s", path, exc_info=True)
        return None
    lines = text.splitlines()
    for line in reversed(lines[-_MAX_TAIL_LINES:]):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        ts = record.get("timestamp")
        if not isinstance(ts, str):
            continue
        try:
            parsed = datetime.fromisoformat(ts)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    return None


def check_healthz(url: str, timeout: float) -> bool:
    """Best-effort HTTP GET — True on any 2xx/3xx response, False otherwise.

    Offline-safe: this hits localhost, so no real network/internet access is
    required; any connection error, timeout, or non-2xx/3xx status counts as
    "down" — mirrors a ``curl --fail --max-time`` health check.
    """
    # Reject anything but http(s) before it ever reaches urlopen — bandit's
    # B310 exists precisely because urlopen() also honours file:// and other
    # unexpected schemes; --healthz-url is operator-supplied (CLI flag / env
    # var / knob), not a hardcoded constant, so this check is load-bearing,
    # not decorative.
    if urllib.parse.urlparse(url).scheme not in {"http", "https"}:
        return False
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # nosec B310
            return 200 <= resp.status < 400
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def read_marker(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read marker %s — treating as absent", path)
        return None
    return data if isinstance(data, dict) else None


def write_marker(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def clear_marker(path: Path) -> None:
    path.unlink(missing_ok=True)


def read_knob_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Could not read knob file %s", path, exc_info=True)
        return {}
    return parse_knob_file(text)


def send_notification(message: str, *, dry_run: bool) -> None:
    """Best-effort macOS notification via osascript. Never raises."""
    if dry_run:
        logger.info("[dry-run] would notify: %s", message)
        return
    script = f'display notification "{message}" with title "HydraFlow Liveness"'
    try:
        subprocess.run(  # noqa: S603
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        logger.warning("osascript notification failed", exc_info=True)


def attempt_restart(knob: dict[str, str], *, dry_run: bool) -> None:
    """Run the operator-configured restart action. Never raises.

    Deliberately never invokes a shell (no ``shell=True``): ``RESTART_COMMAND``
    is split with :func:`shlex.split` into an argv list instead, so a knob
    file can't smuggle shell metacharacters into an injection even though its
    contents are operator-authored, not attacker input.
    """
    command = knob.get("RESTART_COMMAND", "").strip()
    label = knob.get("RESTART_LABEL", "").strip()
    if command:
        try:
            argv = shlex.split(command)
        except ValueError:
            logger.warning("RESTART_COMMAND could not be parsed: %r", command)
            return
        if not argv:
            logger.warning("RESTART_COMMAND is empty after parsing: %r", command)
            return
    elif label:
        uid = os.getuid()
        argv = ["launchctl", "kickstart", "-k", f"gui/{uid}/{label}"]
    else:
        logger.warning(
            "RESTART_ENABLED=true but no RESTART_COMMAND/RESTART_LABEL "
            "configured — skipping restart"
        )
        return

    if dry_run:
        logger.info("[dry-run] would run restart action: %r", argv)
        return
    try:
        subprocess.run(  # noqa: S603
            argv,
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        logger.warning("Restart action failed", exc_info=True)


# --------------------------------------------------------------------------
# Tier-1 boot-correctness kernel (#10734): boot-SHA/branch guard, orphan reaper,
# stuck-credit probe, and the reboot actuator. All bounded + failure-tolerant.
# --------------------------------------------------------------------------


def _control_url(port: int, path: str) -> str:
    return f"http://127.0.0.1:{port}{path}"


def http_post_status(
    url: str, *, timeout: float = _HTTP_POST_TIMEOUT_SECONDS
) -> str | None:
    """POST an empty body to a control endpoint; return the reply's ``status``.

    Best-effort and bounded: a non-http scheme, connection error, timeout, or
    unparseable body yields None. Used for ``/api/control/start`` (reply status
    "started") and ``/api/control/credit-refresh" (status "resuming" /
    "still_exhausted" / "not_paused").
    """
    if urllib.parse.urlparse(url).scheme not in {"http", "https"}:
        return None
    request = urllib.request.Request(url, data=b"", method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # nosec B310
            if not (200 <= resp.status < 400):
                return None
            body = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(data, dict):
        status = data.get("status")
        return status if isinstance(status, str) else None
    return None


def find_port_listener_pids(
    port: int, *, timeout: float = _LSOF_TIMEOUT_SECONDS
) -> list[int]:
    """PIDs listening on ``tcp:<port>`` via ``lsof``, or [] (best-effort, bounded).

    No pidfile exists in HydraFlow, so the running server is located by the port
    it holds. A missing ``lsof`` (non-macOS/Linux), non-zero exit, or timeout
    degrades to an empty list — the relaunch below still spawns a fresh clone.
    """
    try:
        result = subprocess.run(  # noqa: S603
            ["lsof", "-ti", f"tcp:{port}"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    pids: list[int] = []
    for token in result.stdout.split():
        try:
            pids.append(int(token.strip()))
        except ValueError:
            continue
    return pids


def _terminate_pid_group(pid: int) -> None:
    """Best-effort SIGKILL of ``pid``'s whole process group; never raises.

    Reuses the reaper's ``is_reapable_pid`` guard (positive-int / not-init /
    not-self) so a fabricated or stale lsof pid can never SIGKILL init or the
    kernel's own group.
    """
    if not orphan_reaper.is_reapable_pid(pid):
        return
    try:
        pgid = os.getpgid(pid)
    except (ProcessLookupError, OSError):
        pgid = pid
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, OSError):
        logger.warning("Could not signal process group of pid %s", pid, exc_info=True)


def reboot_factory(
    *,
    workspace: Path,
    factory_branch: str,
    dashboard_port: int,
    launcher: Path = _LAUNCHER_SCRIPT,
    dry_run: bool,
) -> bool:
    """Force-resync + relaunch the isolated factory pinned to ``factory_branch``.

    Kills the process group holding ``dashboard_port`` (there is no pidfile),
    then spawns ``run-factory-isolated.sh`` **detached** — the launcher
    ``exec make run``s and never returns, so it must not be waited on (a
    ``subprocess.run`` with a timeout would kill the relaunch). Returns True when
    a relaunch was spawned (or would be, in dry-run). Never raises.
    """
    if dry_run:
        logger.info(
            "[dry-run] would reboot factory on port %s -> branch %s (workspace %s)",
            dashboard_port,
            factory_branch,
            workspace,
        )
        return True
    for pid in find_port_listener_pids(dashboard_port):
        _terminate_pid_group(pid)
    if not launcher.exists():
        logger.error("Launcher script missing: %s — cannot relaunch", launcher)
        return False
    env = {
        **os.environ,
        "HYDRAFLOW_FACTORY_BRANCH": factory_branch,
        "HYDRAFLOW_FACTORY_WORKSPACE": str(workspace),
    }
    try:
        subprocess.Popen(  # noqa: S603
            ["bash", str(launcher)],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # detach so the kernel's own exit can't kill it
        )
    except (OSError, subprocess.SubprocessError):
        logger.warning("Factory relaunch spawn failed", exc_info=True)
        return False
    logger.warning(
        "Rebooted factory: force-resync + relaunch on branch %s", factory_branch
    )
    return True


def run_boot_guard(
    *,
    workspace: Path,
    factory_branch: str,
    dashboard_port: int,
    prior_stale_reboot_at: str | None,
    now: datetime,
    dry_run: bool,
) -> tuple[str | None, list[str]]:
    """Boot-correctness guard for one tick.

    Returns ``(new_stale_reboot_at, notify_messages)``. On a definite stale/
    wrong-branch boot it force-resyncs + reboots **at most once per incident**
    (gated by ``stale_reboot_at``); on a verified-correct idle boot it issues a
    single ``POST /api/control/start``; the incident clears (returns None) on any
    healthy, boot-correct tick.
    """
    notify: list[str] = []
    status_url = _control_url(dashboard_port, "/api/control/status")
    decision = boot_guard.probe_boot_correctness(
        workspace=workspace, factory_branch=factory_branch, status_url=status_url
    )
    logger.info("boot-guard: %s (%s)", decision.action.value, decision.reason)

    if decision.action is boot_guard.BootAction.RESYNC_REBOOT:
        if prior_stale_reboot_at is not None:
            # Already rebooted this incident — notify only, never re-spawn (a
            # relaunch that keeps failing must not reboot every 5 minutes).
            notify.append(
                f"HydraFlow factory STILL on a stale boot ({decision.reason}) — "
                f"rebooted at {prior_stale_reboot_at}, not retrying"
            )
            return prior_stale_reboot_at, notify
        notify.append(
            f"HydraFlow factory on a STALE boot ({decision.reason}) — resync+reboot"
        )
        rebooted = reboot_factory(
            workspace=workspace,
            factory_branch=factory_branch,
            dashboard_port=dashboard_port,
            dry_run=dry_run,
        )
        # Record the incident so the next tick does not re-spawn. In dry-run,
        # record nothing (no side effects at all).
        if dry_run:
            return prior_stale_reboot_at, notify
        return (now.isoformat() if rebooted else prior_stale_reboot_at), notify

    if decision.action is boot_guard.BootAction.START:
        if not dry_run:
            reply = http_post_status(_control_url(dashboard_port, "/api/control/start"))
            logger.info("boot-guard: issued /api/control/start -> %s", reply)
        else:
            logger.info("[dry-run] would POST /api/control/start")
        return None, notify

    # NO_ACTION: clear any prior incident marker (boot is correct/already up) but
    # surface a notify when the reason was an unverifiable fact, not a clean boot.
    if decision.notify:
        notify.append(f"HydraFlow boot-guard could not verify boot: {decision.reason}")
    return None, notify


def run_orphan_reaper(*, dry_run: bool) -> list[int]:
    """Reap orphaned (ppid==1) pytest workers left by a dead/OOM'd build.

    Returns the reaped pids (or, in dry-run, the pids that would be reaped).
    """
    ps_output = orphan_reaper.enumerate_processes()
    if ps_output is None:
        return []
    pids = orphan_reaper.select_orphan_pids(ps_output)
    if not pids:
        return []
    if dry_run:
        logger.info("[dry-run] would reap orphaned pytest workers: %s", pids)
        return pids
    reaped = orphan_reaper.reap_orphans(pids)
    if reaped:
        logger.warning("Reaped orphaned pytest workers: %s", reaped)
    return reaped


def run_credit_probe(
    *, dashboard_port: int, prior_paused_ticks: int, status: str | None, dry_run: bool
) -> tuple[int, list[str]]:
    """Distinguish a live credit pause from a wedged ``credits_paused_until``.

    Returns ``(new_paused_ticks, notify_messages)``. Only past the consecutive-
    tick threshold does it POST ``/api/control/credit-refresh`` to corroborate;
    a ``still_exhausted`` reply leaves the pause in place.
    """
    notify: list[str] = []
    decision = credit_probe.classify_credit_pause(
        status=status, paused_ticks=prior_paused_ticks
    )
    if decision.action is not credit_probe.CreditAction.REQUEST_REFRESH:
        return decision.paused_ticks, notify

    if dry_run:
        logger.info("[dry-run] would probe stuck credit pause via credit-refresh")
        return decision.paused_ticks, notify

    reply = http_post_status(
        _control_url(dashboard_port, "/api/control/credit-refresh")
    )
    outcome = credit_probe.interpret_refresh_response(reply)
    logger.info("credit-probe: refresh -> %s (%s)", reply, outcome.value)
    if outcome is credit_probe.RefreshOutcome.CONFIRMED_EXHAUSTED:
        notify.append(
            "HydraFlow credit pause persists and the backend confirms the account "
            "is still exhausted — leaving it paused (genuine pause, not a wedge)"
        )
    else:
        notify.append("HydraFlow cleared a stuck credit pause (backend resumed)")
    return decision.paused_ticks, notify


def _discover_events_path(base: Path = _REPO_ROOT) -> Path | None:
    """Best-effort default: flat ``.hydraflow/events.jsonl``, else the
    newest ``.hydraflow/*/events.jsonl`` (repo-scoped layout).

    ``base`` defaults to the installed script's repo but is pointed at the
    ``--workspace`` clone when set, so staleness is read from where the factory
    actually runs, not the dev checkout the watchdog is installed into (#10734).
    """
    flat = base / ".hydraflow" / "events.jsonl"
    if flat.exists():
        return flat
    candidates = sorted(
        (base / ".hydraflow").glob("*/events.jsonl"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    return candidates[0] if candidates else None


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--healthz-url",
        default=os.environ.get("HYDRAFLOW_LIVENESS_HEALTHZ_URL", _DEFAULT_HEALTHZ_URL),
    )
    parser.add_argument(
        "--events-path",
        default=os.environ.get("HYDRAFLOW_LIVENESS_EVENTS_PATH", ""),
        help="Path to events.jsonl. Auto-discovered under .hydraflow/ if omitted.",
    )
    parser.add_argument(
        "--stale-seconds",
        type=float,
        default=float(
            os.environ.get("HYDRAFLOW_LIVENESS_STALE_SECONDS", _DEFAULT_STALE_SECONDS)
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(
            os.environ.get(
                "HYDRAFLOW_LIVENESS_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS
            )
        ),
    )
    parser.add_argument(
        "--marker-path",
        type=Path,
        default=Path(
            os.environ.get("HYDRAFLOW_LIVENESS_MARKER_PATH", str(_DEFAULT_MARKER_PATH))
        ),
    )
    parser.add_argument(
        "--knob-path",
        type=Path,
        default=Path(
            os.environ.get("HYDRAFLOW_LIVENESS_KNOB_PATH", str(_DEFAULT_KNOB_PATH))
        ),
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=(
            Path(os.environ["HYDRAFLOW_FACTORY_WORKSPACE"])
            if os.environ.get("HYDRAFLOW_FACTORY_WORKSPACE")
            else None
        ),
        help="Isolated factory workspace clone. When set, enables the Tier-1 "
        "boot-correctness guard, orphan reaper, and stuck-credit probe; events "
        "staleness is read from here. Omit for the legacy notify-only watchdog. "
        f"Production installs pass {_DEFAULT_WORKSPACE}.",
    )
    parser.add_argument(
        "--factory-branch",
        default=os.environ.get("HYDRAFLOW_FACTORY_BRANCH", _DEFAULT_FACTORY_BRANCH),
        help="Branch the factory must run on (ADR-0042: staging). A stale/wrong-"
        "branch boot is force-resynced to this branch before any start.",
    )
    parser.add_argument(
        "--dashboard-port",
        type=int,
        default=int(
            os.environ.get("HYDRAFLOW_DASHBOARD_PORT", _DEFAULT_DASHBOARD_PORT)
        ),
        help="Port the factory dashboard/API listens on (control status/start/"
        "credit-refresh + the reboot's process-group lookup).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute the decision and log it, but never call osascript/launchctl, "
        "never reboot/start/reap, and never write/clear the marker file.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    args = build_arg_parser().parse_args(argv)

    # Read events staleness from the isolated factory workspace when known —
    # the watchdog is installed into the dev checkout, but the factory runs from
    # its own clone, whose events.jsonl is the live signal (#10734).
    events_base = args.workspace if args.workspace is not None else _REPO_ROOT
    events_path = (
        Path(args.events_path)
        if args.events_path
        else _discover_events_path(events_base)
    )

    healthz_ok = check_healthz(args.healthz_url, args.timeout_seconds)
    now = datetime.now(UTC)
    events_age_seconds: float | None = None
    if events_path is not None:
        last_ts = read_last_jsonl_timestamp(events_path)
        if last_ts is not None:
            events_age_seconds = (now - last_ts).total_seconds()

    marker = read_marker(args.marker_path)
    knob = read_knob_file(args.knob_path)
    restart_enabled = is_restart_enabled(knob)

    decision = decide(
        healthz_ok=healthz_ok,
        events_age_seconds=events_age_seconds,
        stale_threshold_seconds=args.stale_seconds,
        marker=marker,
        restart_enabled=restart_enabled,
        now=now,
    )

    logger.info(
        "healthz_ok=%s events_age_seconds=%s is_down=%s",
        healthz_ok,
        events_age_seconds,
        decision.is_down,
    )

    if decision.should_notify:
        logger.warning(decision.notify_message)
        send_notification(decision.notify_message, dry_run=args.dry_run)

    if decision.should_restart:
        attempt_restart(knob, dry_run=args.dry_run)

    # --- Tier-1 boot-correctness kernel (#10734), active only with --workspace ---
    new_stale_reboot_at: str | None = None
    new_paused_ticks = 0
    kernel_notifications: list[str] = []
    if args.workspace is not None:
        raw_sra = marker.get("stale_reboot_at") if marker else None
        prior_stale_reboot_at = raw_sra if isinstance(raw_sra, str) else None
        new_stale_reboot_at, boot_notify = run_boot_guard(
            workspace=args.workspace,
            factory_branch=args.factory_branch,
            dashboard_port=args.dashboard_port,
            prior_stale_reboot_at=prior_stale_reboot_at,
            now=now,
            dry_run=args.dry_run,
        )

        raw_ticks = marker.get("paused_ticks", 0) if marker else 0
        prior_paused_ticks = (
            raw_ticks
            if isinstance(raw_ticks, int) and not isinstance(raw_ticks, bool)
            else 0
        )
        status_json = boot_guard.fetch_control_status(
            _control_url(args.dashboard_port, "/api/control/status")
        )
        status_str = (
            boot_guard.extract_status_fields(status_json)[0]
            if status_json is not None
            else None
        )
        new_paused_ticks, credit_notify = run_credit_probe(
            dashboard_port=args.dashboard_port,
            prior_paused_ticks=prior_paused_ticks,
            status=status_str,
            dry_run=args.dry_run,
        )

        run_orphan_reaper(dry_run=args.dry_run)
        kernel_notifications = boot_notify + credit_notify

    for message in kernel_notifications:
        logger.warning(message)
        send_notification(message, dry_run=args.dry_run)

    if not args.dry_run:
        # Merge the down-detection marker with the kernel's incident fields so a
        # boot-correctness reboot / stuck-pause counter survives a healthy
        # down-detection tick (which alone would clear the file).
        final_marker: dict[str, object] = (
            dict(decision.new_marker) if decision.new_marker else {}
        )
        if new_stale_reboot_at is not None:
            final_marker["stale_reboot_at"] = new_stale_reboot_at
        if new_paused_ticks:
            final_marker["paused_ticks"] = new_paused_ticks
        if final_marker:
            write_marker(args.marker_path, final_marker)
        else:
            clear_marker(args.marker_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
