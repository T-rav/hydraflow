"""pytest plugin: name and stack-dump any test that outruns a wall-clock budget.

Born from a 33-minute hang (2026-08-29) in which one xdist worker burned a
core while seven idled, and NOTHING in the output said which test it was.
Identifying it afterwards took two hours of tmp-dir forensics and produced a
wrong attribution on the way. This plugin answers that question in the first
minute instead.

Why not just ``--timeout``: that is the right tool for *ending* a hang, and
the lanes set it. But it kills the test, so the stack is gone, and it cannot
name a test wedged inside one long C-level call because the signal is only
delivered between bytecodes. This watchdog is complementary — it never
interrupts anything. A daemon *thread* calls ``faulthandler.dump_traceback``,
which does not require the GIL, so it reports even while the main thread is
wedged in a non-yielding loop, and it cannot be swallowed by a broad
``except BaseException``.

Enabled with ``-p tests.hf_spin_watch``. Knobs:

  HF_SPIN_TIMEOUT  seconds one test may run before its first dump (default 180)
  HF_SPIN_OUT      output path prefix (default /tmp/hf_spin)

Under xdist each worker arms its own watchdog and writes ``<prefix>-<pid>.txt``,
so the file name identifies the worker. Dumps repeat on each doubling of the
budget, which is what distinguishes a slow test from a non-terminating one:
a slow test dumps once and finishes; a wedged one keeps dumping.
"""

from __future__ import annotations

import faulthandler
import os
import threading
import time

import pytest

_DEFAULT_TIMEOUT_S = 180.0
_POLL_INTERVAL_S = 1.0

_lock = threading.Lock()
_state: dict[str, object] = {
    "nodeid": "<session: import/collect>",
    "started": time.monotonic(),
    "dumped": 0,
    # False whenever no test is executing: collection, and the gaps between
    # tests. Dumping then reports an IDLE process, which the plugin's own
    # first live run did twice — an xdist worker that loadscope gave no work
    # sat at the sentinel and dumped itself. An instrument that cries wolf
    # gets ignored, so it only speaks while a test is actually running.
    "in_test": False,
    # Guards against arming twice when pytest_configure runs more than once
    # (xdist workers, nested sessions). Kept in the locked dict rather than a
    # module global so there is exactly one piece of mutable module state.
    "armed": False,
}


def _timeout_s() -> float:
    try:
        return float(os.environ.get("HF_SPIN_TIMEOUT", _DEFAULT_TIMEOUT_S))
    except ValueError:
        return _DEFAULT_TIMEOUT_S


def _out_prefix() -> str:
    return os.environ.get("HF_SPIN_OUT", "/tmp/hf_spin")


def _watch(timeout_s: float, out_prefix: str) -> None:
    path = f"{out_prefix}-{os.getpid()}.txt"
    while True:
        time.sleep(_POLL_INTERVAL_S)
        with _lock:
            if not _state["in_test"]:
                continue
            nodeid = _state["nodeid"]
            started = float(_state["started"])  # type: ignore[arg-type]
            dumped = int(_state["dumped"])  # type: ignore[arg-type]
        elapsed = time.monotonic() - started
        if elapsed <= timeout_s * (2**dumped):
            continue
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(
                    f"\n==== hf-spin-watch pid={os.getpid()} "
                    f"elapsed={elapsed:.0f}s dump#{dumped + 1} :: {nodeid}\n"
                )
                fh.flush()
                faulthandler.dump_traceback(file=fh, all_threads=True)
                fh.flush()
        except OSError:
            # A watchdog must never be the reason a run fails.
            pass
        with _lock:
            # Only advance if we are still on the same test; otherwise the
            # next test's own budget starts fresh in pytest_runtest_protocol.
            if _state["nodeid"] == nodeid:
                _state["dumped"] = dumped + 1


def pytest_configure(config: pytest.Config) -> None:
    with _lock:
        if _state["armed"]:
            return
        _state["armed"] = True
    threading.Thread(
        target=_watch,
        args=(_timeout_s(), _out_prefix()),
        name="hf-spin-watch",
        daemon=True,
    ).start()


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None):
    """Track the current nodeid, reruns included (this fires per attempt)."""
    with _lock:
        _state["nodeid"] = item.nodeid
        _state["started"] = time.monotonic()
        _state["dumped"] = 0
        _state["in_test"] = True
    yield
    with _lock:
        _state["in_test"] = False
        _state["nodeid"] = f"<between tests, after {item.nodeid}>"
        _state["started"] = time.monotonic()
        _state["dumped"] = 0
