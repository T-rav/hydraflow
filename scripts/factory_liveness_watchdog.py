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

Usage::

    scripts/factory_liveness_watchdog.py [--dry-run]
        [--healthz-url URL] [--events-path PATH]
        [--stale-seconds N] [--timeout-seconds N]
        [--marker-path PATH] [--knob-path PATH]

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
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

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


def _discover_events_path() -> Path | None:
    """Best-effort default: flat ``.hydraflow/events.jsonl``, else the
    newest ``.hydraflow/*/events.jsonl`` (repo-scoped layout)."""
    flat = _REPO_ROOT / ".hydraflow" / "events.jsonl"
    if flat.exists():
        return flat
    candidates = sorted(
        (_REPO_ROOT / ".hydraflow").glob("*/events.jsonl"),
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
        "--dry-run",
        action="store_true",
        help="Compute the decision and log it, but never call osascript/launchctl "
        "and never write/clear the marker file.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    args = build_arg_parser().parse_args(argv)

    events_path = (
        Path(args.events_path) if args.events_path else _discover_events_path()
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

    if not args.dry_run:
        if decision.new_marker is None:
            clear_marker(args.marker_path)
        else:
            write_marker(args.marker_path, decision.new_marker)

    return 0


if __name__ == "__main__":
    sys.exit(main())
