"""Shared file-writing utilities for HydraFlow."""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from secret_scrub import scrub_secrets

logger = logging.getLogger("hydraflow.file_util")


# In-process fairness gate for file_lock() (issue #9661 follow-up). fcntl.flock
# only arbitrates *across processes*; polling it with LOCK_NB gives no
# ordering guarantee among threads *within this process* — a plain
# ``threading.Lock`` doesn't either (CPython does not guarantee FIFO wakeup
# order), so a bursty thread that keeps winning the non-blocking re-acquire
# race can starve a thread that backed off to sleep between polls, even
# though the OS's own blocking flock() wait queue would have woken the
# longest-waiting thread first. ``_FifoLock`` restores that ordering
# deterministically: whichever caller reaches ``acquire()`` first is served
# first, no matter how many later callers pile up behind it. Unlike
# ``fcntl.flock(LOCK_EX)``, its ``acquire(timeout=...)`` always returns.
class _FifoLock:
    """Ticket-based mutex serving waiters in strict arrival order."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._next_ticket = 0
        self._serving = 0
        self._abandoned: set[int] = set()

    def _skip_abandoned_locked(self) -> None:
        # Advance _serving past tickets whose holders timed out; without this
        # a single abandoned ticket wedges the gate forever (nobody releases
        # a slot that was never served). Caller must hold self._cond.
        while self._serving in self._abandoned:
            self._abandoned.discard(self._serving)
            self._serving += 1

    def acquire(self, timeout: float) -> bool:
        with self._cond:
            ticket = self._next_ticket
            self._next_ticket += 1
            deadline = time.monotonic() + timeout
            while self._serving != ticket:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    # Never got served: mark our slot abandoned so the serving
                    # counter skips it when it gets here (see release()).
                    self._abandoned.add(ticket)
                    self._cond.notify_all()
                    return False
                self._cond.wait(remaining)
            return True

    def release(self) -> None:
        with self._cond:
            self._serving += 1
            self._skip_abandoned_locked()
            self._cond.notify_all()


_thread_gate_registry: dict[str, _FifoLock] = {}
_thread_gate_registry_lock = threading.Lock()


def _thread_gate(path: Path) -> _FifoLock:
    """Return the process-local FIFO lock guarding *path*, creating if needed."""
    key = str(path)
    with _thread_gate_registry_lock:
        gate = _thread_gate_registry.get(key)
        if gate is None:
            gate = _FifoLock()
            _thread_gate_registry[key] = gate
        return gate


# Default bound on file_lock() acquisition (issue #9661). asyncio.to_thread
# dispatches blocking work onto the default ThreadPoolExecutor; asyncio.wait_for
# / asyncio.timeout can only cancel the *awaiting coroutine*, never the running
# worker thread, so a blocking fcntl.flock(LOCK_EX) that never returns pins a
# pool worker forever. Enough pinned workers exhaust the pool and hang every
# later to_thread call process-wide (root cause of the #9600 fleet stall).
# 30s is generous relative to every known critical section behind file_lock()
# (the longest is EventLog._rotate_sync's read -> filter -> atomic_write of the
# whole event log, a local-FS rewrite that completes in well under a second
# even at hundreds of MB) while still bounding the worker deterministically.
DEFAULT_FILE_LOCK_TIMEOUT = 30.0


class FileLockTimeout(TimeoutError):
    """Raised when ``file_lock`` cannot acquire within its deadline.

    Subclasses ``TimeoutError``, which PEP 3151 makes a subclass of
    ``OSError`` — so every existing ``except OSError`` caller of ``file_lock``
    (events, metrics_manager, prompt_telemetry, audit_chain, ...) catches this
    and degrades gracefully instead of hanging or crashing with an unexpected
    exception type.
    """


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
def file_lock(
    path: Path,
    *,
    timeout: float | None = None,
    poll_interval: float = 0.02,
) -> Iterator[None]:
    """Acquire an exclusive advisory lock for *path* until context exit.

    Self-bounding (issue #9661): acquisition first takes a process-local
    ``_FifoLock`` for *path* (see ``_thread_gate``), then polls a
    non-blocking ``fcntl.flock(LOCK_EX | LOCK_NB)`` against a monotonic
    deadline instead of blocking indefinitely on a bare ``LOCK_EX``. Both
    stages share the same deadline. This runs inside ``asyncio.to_thread``
    for most callers, where a blocking-forever acquire would pin a worker in
    the default ``ThreadPoolExecutor`` permanently — ``asyncio.wait_for`` /
    ``asyncio.timeout`` cancel only the awaiting coroutine, never a running
    thread, so enough wedged holders eventually hang every later
    ``to_thread`` call process-wide (the #9600 fleet stall).

    The ``_FifoLock`` stage exists because ``fcntl.flock`` only arbitrates
    *across processes*; polling it gives no fairness guarantee among
    *threads in this process* (nor does a plain ``threading.Lock`` — CPython
    does not guarantee FIFO wakeup order), so a bursty repeat-acquirer could
    otherwise starve a thread that backed off to sleep between polls
    (unlike the OS's own blocking flock() wait queue, which wakes the
    longest-waiting thread first). ``_FifoLock.acquire(timeout=...)``
    restores that ordering deterministically for the common single-process
    case while staying safely bounded — unlike ``fcntl.flock(LOCK_EX)``, it
    always returns. *poll_interval* is a blocking ``time.sleep`` between the
    flock polls, which is fine here because this function is only ever
    meant to run off the event loop.

    Raises ``FileLockTimeout`` (a ``TimeoutError`` / ``OSError``) if the lock
    cannot be acquired before the deadline. Defaults to
    ``DEFAULT_FILE_LOCK_TIMEOUT`` (30s); pass *timeout* to override for a
    caller with different needs.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    bound = DEFAULT_FILE_LOCK_TIMEOUT if timeout is None else timeout
    deadline = time.monotonic() + bound

    gate = _thread_gate(path)
    if not gate.acquire(timeout=max(0.0, deadline - time.monotonic())):
        raise FileLockTimeout(f"Timed out after {bound}s acquiring file lock: {path}")
    try:
        with open(path, "a+", encoding="utf-8") as lock_f:
            fd = lock_f.fileno()
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise FileLockTimeout(
                            f"Timed out after {bound}s acquiring file lock: {path}"
                        ) from None
                    time.sleep(poll_interval)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        gate.release()


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
