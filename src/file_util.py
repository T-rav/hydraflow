"""Shared file-writing utilities for HydraFlow."""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from secret_scrub import scrub_secrets

logger = logging.getLogger("hydraflow.file_util")


def atomic_write(path: Path, data: str) -> None:
    """Write *data* to *path* atomically via temp file + ``os.replace``.

    Creates parent directories if needed.  The temp file is placed in the
    same directory as *path* so that ``os.replace`` is guaranteed to be
    atomic on POSIX (same filesystem).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.stem}-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def append_jsonl(path: Path, data: str) -> None:
    """Append *data* as a single scrubbed line to *path* with crash-safe fsync.

    Creates parent directories if needed.  Secrets are redacted (ADR-0085) so a
    leaked credential never persists in the canonical audit/transcript/event
    stream, then ``flush`` + ``fsync`` ensure the record reaches stable storage
    before returning.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(scrub_secrets(data) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _parse_row_timestamp(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp value from a jsonl row; ``None`` if unparseable.

    ``datetime.fromisoformat`` on Python 3.11+ accepts both serialization
    forms Pydantic emits for UTC datetimes (``...56Z`` when microseconds are
    0, ``...56.000001Z`` otherwise). Naive datetimes are assumed UTC so
    comparisons against aware ones never raise ``TypeError``.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def is_newer_timestamp(candidate: object, existing: object) -> bool:
    """Return True when *candidate* is a strictly newer timestamp than *existing*.

    The shared "parse ts, latest-wins" rule for jsonl rows — used by both
    ``compact_jsonl_latest_by_key`` and the dashboard conformance route so
    the two can't drift. Timestamps are compared as parsed datetimes, never
    as strings: Pydantic serializes whole-second UTC datetimes as ``...56Z``
    but sub-second ones as ``...56.000001Z``, and lexically ``.`` < ``Z``
    would sort the newer row first. Unparseable/missing timestamps are
    treated as oldest: an unparseable *candidate* is never newer, and a
    parseable *candidate* always beats an unparseable *existing*. Equal
    timestamps are not newer (the first row seen wins).
    """
    cand = _parse_row_timestamp(candidate)
    if cand is None:
        return False
    exist = _parse_row_timestamp(existing)
    if exist is None:
        return True
    return cand > exist


def compact_jsonl_latest_by_key(path: Path, *, key: str, ts_key: str) -> None:
    """Rewrite jsonl *path* in place, keeping only the newest row per *key*.

    Retention policy for **snapshot-semantics** jsonl files — files where
    only the latest row per key is ever served (e.g.
    ``metrics/adr_conformance.jsonl``, ADR-0100's gitignored scratch state).
    Do NOT use on trend-semantics files (e.g. ``fitness.jsonl``) where row
    history is load-bearing.

    Rows are JSON objects, one per line. For each distinct value of *key*
    the row whose *ts_key* is latest per ``is_newer_timestamp`` survives,
    preserving first-seen key order. Blank lines, corrupt/non-object lines,
    and rows missing *key* are dropped without raising (the same tolerance
    as the dashboard read path). The rewrite goes through ``atomic_write``
    (tempfile in the same directory + ``os.replace``), so a concurrent
    reader sees either the old or the new complete file, never a torn one.
    A missing file is a no-op.
    """
    if not path.exists():
        return

    kept: dict[str, tuple[str, object]] = {}  # key value -> (raw line, ts value)
    with open(path, encoding="utf-8") as f:
        for raw_line in f:
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError:
                logger.debug(
                    "Dropping corrupt jsonl line during compaction of %s", path
                )
                continue
            if not isinstance(row, dict):
                continue
            key_value = row.get(key)
            if not key_value:
                continue
            existing = kept.get(str(key_value))
            if existing is None or is_newer_timestamp(row.get(ts_key), existing[1]):
                kept[str(key_value)] = (stripped, row.get(ts_key))

    atomic_write(path, "".join(f"{line}\n" for line, _ts in kept.values()))


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Acquire an exclusive advisory lock for *path* until context exit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as lock_f:
        fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)


def rotate_backups(path: Path, count: int = 3) -> None:
    """Rotate backup copies of *path*, keeping at most *count* generations.

    Copies ``path`` to ``path.bak``, shifting existing ``.bak`` files:
    ``.bak`` -> ``.bak.1``, ``.bak.1`` -> ``.bak.2``, etc.  Deletes
    the oldest backup beyond *count*.
    """
    if not path.exists():
        return

    # Delete the oldest backup if it exists
    oldest = Path(f"{path}.bak.{count}")
    if oldest.exists():
        try:
            oldest.unlink()
        except OSError:
            logger.warning("Could not remove oldest backup %s", oldest, exc_info=True)

    # Shift existing backups up: .bak.(n-1) -> .bak.n
    for i in range(count - 1, 0, -1):
        src = Path(f"{path}.bak.{i}")
        dst = Path(f"{path}.bak.{i + 1}")
        if src.exists():
            try:
                shutil.copy2(src, dst)
                src.unlink()
            except OSError:
                logger.warning(
                    "Could not rotate backup %s -> %s", src, dst, exc_info=True
                )

    # Shift .bak -> .bak.1
    bak = Path(f"{path}.bak")
    if bak.exists():
        try:
            shutil.copy2(bak, Path(f"{path}.bak.1"))
            bak.unlink()
        except OSError:
            logger.warning("Could not rotate backup %s", bak, exc_info=True)

    # Copy current file to .bak
    try:
        shutil.copy2(path, bak)
    except OSError:
        logger.warning("Could not create backup %s", bak, exc_info=True)
