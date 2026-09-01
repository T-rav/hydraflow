"""Emit this factory's vitals document to a local append-only spool (#11690).

Layer 2 of the three-layer strategy: **transport, with no opinion about sinks.**
`scripts/emit_vitals.py` writes one self-identifying JSON document to stdout and
knows nothing about where it goes (Layer 1, #11689). This module decides only
*when* it runs and *where the bytes land locally*; shipping them onward is an
adapter's job, deliberately outside HydraFlow, so swapping a sink is never a
HydraFlow change.

**Why the factory host and not CI.** The document's whole value is identity —
`repo`, `head_sha`, `host`. Two hosts reporting the same counter are the same
fact or two different facts depending entirely on which factory produced it,
and no consumer can recover that afterwards. Emitting from a CI runner would
stamp the runner's hostname and answer a question nobody asked.

**When (decision D2).** On every RC cut, plus a time floor. The RC cut is
already the repo's "state changed meaningfully" event, so it needs no new
concept; the floor keeps a quiet factory distinguishable from a dead one, which
is the single thing a push-based aggregate cannot infer for itself.

Decisions D1 (push vs pull) and D3 (sink) are NOT taken here and are not
HydraFlow's to take — an adapter reading this spool can push or be scraped, to
any sink, without touching this file.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from package_resources import ResourceNotFoundError, checkout_path
from subprocess_util import run_subprocess_result

if TYPE_CHECKING:  # pragma: no cover - typing only
    from config import HydraFlowConfig

logger = logging.getLogger(__name__)

#: Bounded so a wedged emitter can never hold a loop tick open.
_EMIT_TIMEOUT_S = 60


def spool_path(config: HydraFlowConfig) -> Path:
    """The append-only JSONL spool an adapter reads."""
    return Path(config.data_root) / "vitals" / "spool.jsonl"


def _stamp_path(config: HydraFlowConfig) -> Path:
    return Path(config.data_root) / "memory" / ".vitals_last_emit"


def read_last_emit(config: HydraFlowConfig) -> datetime | None:
    """When this factory last emitted, or None if never / unreadable."""
    path = _stamp_path(config)
    if not path.exists():
        return None
    try:
        stamped = datetime.fromisoformat(path.read_text().strip())
    except (OSError, ValueError):
        return None
    return stamped if stamped.tzinfo else stamped.replace(tzinfo=UTC)


def floor_elapsed(
    last_emit: datetime | None, now: datetime, floor_hours: float
) -> bool:
    """Has the time floor passed? **Pure** — no clock read, no filesystem.

    Never emitted counts as elapsed: a factory that has never reported is the
    case the floor exists to make visible, not one to wait a further day on.

    A non-positive floor disables the floor entirely, leaving RC cuts as the
    only trigger. That is a real configuration — a factory that cuts RCs often
    needs no heartbeat — rather than an accident of arithmetic.
    """
    if floor_hours <= 0:
        return False
    if last_emit is None:
        return True
    return (now - last_emit).total_seconds() / 3600 >= floor_hours


def _resolve_emitter(config: HydraFlowConfig) -> tuple[Path, Path] | None:
    """The (script, cwd) to run, or None if this factory should not emit.

    Split out to keep each function under PLR0911's six-return cap without a
    suppression. Every branch here is a legitimate "nothing to emit", never an
    error: emission is observation, and observation that breaks its caller —
    an RC cut — is worse than no observation.
    """
    # `is not True`, not truthiness: a MagicMock config answers ANY attribute
    # with a truthy Mock, and that is the config shape most loop tests use.
    if getattr(config, "vitals_emit_enabled", False) is not True:
        return None
    try:
        script = checkout_path("scripts", "emit_vitals.py")
    except ResourceNotFoundError:
        # Absent from a wheel install by design; nothing to emit, not an error.
        logger.debug("vitals: emitter script unavailable — skipping")
        return None
    cwd = Path(config.repo_root)
    if not cwd.is_dir():
        # `run_subprocess_result` raises FileNotFoundError before it can return
        # a result when cwd is absent, so checking the result is not enough.
        logger.debug("vitals: repo_root %s is not a directory — skipping", cwd)
        return None
    return script, cwd


async def _render_document(config: HydraFlowConfig) -> dict[str, Any] | None:
    """Run the emitter and parse its document, or None on any failure path.

    Split from :func:`emit_to_spool` so each half stays under PLR0911's
    six-return cap without a suppression — the ratchet only shrinks.
    """
    resolved = _resolve_emitter(config)
    if resolved is None:
        return None
    script, cwd = resolved

    try:
        result = await run_subprocess_result(
            sys.executable, str(script), timeout=_EMIT_TIMEOUT_S, cwd=cwd
        )
    except OSError:
        logger.warning("vitals: emitter could not be spawned", exc_info=True)
        return None

    if result is None or result.returncode != 0:
        logger.warning(
            "vitals: emitter failed (rc=%s) — no document spooled",
            getattr(result, "returncode", "no-result"),
        )
        return None
    try:
        parsed = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        logger.warning("vitals: emitter produced no parseable document")
        return None
    return parsed if isinstance(parsed, dict) else None


async def emit_to_spool(
    config: HydraFlowConfig, *, now: datetime, reason: str
) -> Path | None:
    """Append one vitals document to the spool. Returns its path, or None.

    Every failure path returns None and logs. Vitals emission is observation,
    and observation that can break a promotion tick is worse than no
    observation — the RC cut is the caller, and it must not fail because a
    telemetry document could not be written.

    The flag is checked with ``is not True`` inside :func:`_render_document`: a
    MagicMock config answers ANY attribute with a truthy Mock, and that is the
    config shape most loop tests hand their subject.
    """
    document = await _render_document(config)
    if document is None:
        return None

    # `reason` rides ON the document rather than beside it: an aggregate that
    # cannot tell a cut-triggered reading from a floor heartbeat cannot tell a
    # busy factory from a quiet one, which is the question Layer 3 exists to
    # answer.
    document["trigger"] = reason

    path = spool_path(config)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(document, sort_keys=True) + "\n")
        stamp = _stamp_path(config)
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(now.isoformat())
    except OSError:
        logger.warning("vitals: could not append to spool at %s", path, exc_info=True)
        return None
    logger.info("vitals: spooled a %s reading to %s", reason, path)
    return path
