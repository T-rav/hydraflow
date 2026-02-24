"""Utilities for starting and interacting with the supervisor."""

from __future__ import annotations

import subprocess
import sys
import time

from . import supervisor_client
from .config import STATE_DIR

_SUPERVISOR_LOG = STATE_DIR / "supervisor.log"


def ensure_running() -> None:
    if supervisor_client.ping():
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "hf_cli.supervisor_service"],
        stdout=_SUPERVISOR_LOG.open("a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    start = time.time()
    while time.time() - start < 3:
        if supervisor_client.ping():
            return
        if process.poll() is not None:
            raise RuntimeError("Supervisor exited unexpectedly; see log")
        time.sleep(0.1)
    raise RuntimeError("Timed out waiting for supervisor to start")
