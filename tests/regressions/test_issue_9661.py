"""Regression guard for issue #9661: bound ``file_lock`` against unbounded flock.

Issue #9600's stall traced to ``file_util.file_lock()`` using an unbounded
``fcntl.flock(fd, fcntl.LOCK_EX)`` inside ``asyncio.to_thread``. ``asyncio.
wait_for`` / ``asyncio.timeout`` can only cancel the *awaiting coroutine* —
never the running worker thread — so a blocking ``flock`` acquire that never
returns pins a worker in the default ``ThreadPoolExecutor`` forever. Enough
pinned workers eventually hang every later ``to_thread`` call process-wide.

#9661's fix makes ``file_lock`` self-bounding: it polls a non-blocking
``fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)`` against a monotonic
deadline and raises ``FileLockTimeout`` (a ``TimeoutError`` / ``OSError``)
instead of blocking forever.

This module has two guards:

1. A **static AST scan** over ``src/**/*.py`` that fails if any acquiring
   ``fcntl.flock`` call (mode containing ``LOCK_EX`` or ``LOCK_SH``) omits
   ``LOCK_NB``. ``LOCK_UN`` (release) is exempt. This is the "no new
   unbounded flock call site" CI check the issue asks for.
2. A **runtime proof** that a contended ``file_lock`` under
   ``asyncio.to_thread`` does not exhaust a small ``ThreadPoolExecutor`` —
   the actual behavioral guarantee that directly encodes the #9600 failure
   mode.
"""

from __future__ import annotations

import ast
import asyncio
import concurrent.futures
import fcntl
from pathlib import Path

import pytest

from file_util import FileLockTimeout, file_lock

SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"


def _callee_name(func: ast.expr) -> str | None:
    """Return the simple callee name for ``f(...)`` or ``mod.f(...)``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _lock_flag_names(node: ast.expr) -> set[str]:
    """Collect every ``LOCK_*`` name reachable in *node*'s subtree.

    Handles a bare ``fcntl.LOCK_EX`` (``ast.Attribute``), a bare imported
    ``LOCK_EX`` (``ast.Name``), and a combined ``fcntl.LOCK_EX | fcntl.LOCK_NB``
    (``ast.BinOp`` of ``Attribute``/``Name`` operands).
    """
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr.startswith("LOCK_"):
            names.add(sub.attr)
        elif isinstance(sub, ast.Name) and sub.id.startswith("LOCK_"):
            names.add(sub.id)
    return names


class _UnboundedFlockFinder(ast.NodeVisitor):
    """Collect line numbers of acquiring ``flock`` calls missing ``LOCK_NB``."""

    def __init__(self) -> None:
        self.violations: list[int] = []

    def visit_Call(self, node: ast.Call) -> None:
        if _callee_name(node.func) == "flock" and len(node.args) >= 2:
            mode_flags = _lock_flag_names(node.args[1])
            is_release = "LOCK_UN" in mode_flags
            is_acquire = "LOCK_EX" in mode_flags or "LOCK_SH" in mode_flags
            if is_acquire and not is_release and "LOCK_NB" not in mode_flags:
                self.violations.append(node.lineno)
        self.generic_visit(node)


def _unbounded_flock_lines(tree: ast.Module) -> list[int]:
    finder = _UnboundedFlockFinder()
    finder.visit(tree)
    return finder.violations


# ---------------------------------------------------------------------------
# Static AST guard
# ---------------------------------------------------------------------------


class TestUnboundedFlockFinder:
    """Unit tests for the AST finder against inline fixtures."""

    def test_flags_bare_lock_ex(self) -> None:
        tree = ast.parse("fcntl.flock(fd, fcntl.LOCK_EX)")
        assert _unbounded_flock_lines(tree) == [1]

    def test_flags_bare_lock_sh(self) -> None:
        tree = ast.parse("fcntl.flock(fd, fcntl.LOCK_SH)")
        assert _unbounded_flock_lines(tree) == [1]

    def test_allows_lock_ex_with_lock_nb(self) -> None:
        tree = ast.parse("fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)")
        assert _unbounded_flock_lines(tree) == []

    def test_allows_lock_un_release(self) -> None:
        tree = ast.parse("fcntl.flock(fd, fcntl.LOCK_UN)")
        assert _unbounded_flock_lines(tree) == []

    def test_allows_bare_imported_names(self) -> None:
        tree = ast.parse("flock(fd, LOCK_EX | LOCK_NB)")
        assert _unbounded_flock_lines(tree) == []

    def test_flags_bare_imported_lock_ex_without_lock_nb(self) -> None:
        tree = ast.parse("flock(fd, LOCK_EX)")
        assert _unbounded_flock_lines(tree) == [1]


def test_no_unbounded_flock_acquisitions_in_src() -> None:
    """The live ``src/`` tree must contain zero unbounded ``flock`` acquires.

    ``file_util.file_lock`` is the one sanctioned acquisition site and it
    already ORs in ``LOCK_NB``; this scan fails CI if a future change (in
    ``file_util`` or anywhere else in ``src/``) introduces a new unbounded
    ``fcntl.flock(LOCK_EX)``/``LOCK_SH`` call.
    """
    offenders: dict[str, list[int]] = {}
    for path in sorted(SRC_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        lines = _unbounded_flock_lines(tree)
        if lines:
            offenders[str(path.relative_to(SRC_DIR))] = lines

    assert not offenders, (
        "src/ must not acquire fcntl.flock(LOCK_EX/LOCK_SH) without LOCK_NB — "
        "a blocking acquire inside asyncio.to_thread can pin a "
        "ThreadPoolExecutor worker forever (issue #9661; root cause of the "
        f"#9600 fleet stall). Route through file_util.file_lock() instead. "
        f"Unbounded call sites: {offenders}"
    )


# ---------------------------------------------------------------------------
# Runtime pool-exhaustion proof
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contended_file_lock_does_not_exhaust_thread_pool(
    tmp_path: Path,
) -> None:
    """A held lock must not exhaust the pool — every contender times out.

    Installs a deliberately tiny 2-worker executor, holds the lock from
    outside asyncio, then fires 4 contended ``to_thread(file_lock, ...)``
    calls. Every one must raise ``FileLockTimeout`` (not hang), and — the
    actual #9600 guarantee — an unrelated ``to_thread`` call afterward must
    still complete, proving no worker was left permanently pinned.
    """
    lock_path = tmp_path / "pool.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    loop = asyncio.get_running_loop()
    small_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    loop.set_default_executor(small_pool)
    try:
        with lock_path.open("a+", encoding="utf-8") as holder:
            fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
            try:

                def _try_acquire() -> None:
                    with file_lock(lock_path, timeout=0.2):
                        pass

                results = await asyncio.gather(
                    *(asyncio.to_thread(_try_acquire) for _ in range(4)),
                    return_exceptions=True,
                )
                assert len(results) == 4
                assert all(isinstance(r, FileLockTimeout) for r in results), results
            finally:
                fcntl.flock(holder.fileno(), fcntl.LOCK_UN)

        # The pool must not be exhausted: an unrelated to_thread call still
        # completes promptly.
        proof = await asyncio.wait_for(asyncio.to_thread(lambda: 42), timeout=5.0)
        assert proof == 42
    finally:
        small_pool.shutdown(wait=True)


def test_gate_recovers_after_timeout_abandonment(tmp_path):
    """#9661 wedge pin: a timed-out waiter must not poison the FIFO gate.

    Before the abandoned-ticket fix, a single acquire() timeout left the
    serving counter stuck at the abandoned slot forever — every later
    file_lock() on that path raised FileLockTimeout even with zero
    contention.
    """
    import threading as _threading

    from file_util import FileLockTimeout, file_lock

    lock_path = tmp_path / "wedge.lock"
    entered = _threading.Event()
    release = _threading.Event()

    def _holder() -> None:
        with file_lock(lock_path, timeout=5.0):
            entered.set()
            release.wait(timeout=10.0)

    holder = _threading.Thread(target=_holder)
    holder.start()
    try:
        assert entered.wait(timeout=5.0)
        # Second acquirer times out and abandons its ticket while the
        # holder still owns the gate.
        with pytest.raises(FileLockTimeout), file_lock(lock_path, timeout=0.1):
            pass
    finally:
        release.set()
        holder.join(timeout=10.0)

    # The gate must serve fresh acquirers again — pre-fix this hung/raised.
    with file_lock(lock_path, timeout=2.0):
        pass
