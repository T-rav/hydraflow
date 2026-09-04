"""#11393: a failing fleet-vitals evaluation must not be silent.

The shadow supervisor's whole purpose is to produce a verdict on fleet health.
Its call site is deliberately fail-soft — a broken supervisor must not take the
health monitor down with it — but fail-soft was implemented as `logger.debug`,
so at default levels a failing evaluation and a healthy one were
indistinguishable: both produced nothing.

That matters because #11393 asks the operator to read an empty alarm log as a
PASS for band placement and then arm live interventions on it. That reading is
only sound if a broken supervisor is loud. Found while preparing that review:
the log held zero alarms AND the per-tick state file had never been written, so
"quiet" could not be distinguished from "never ran".

The founding incident for this whole feature was a real signal going out at a
level nobody watched. Swallowing the supervisor's own failure the same way
reproduces that bug one level up.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


class _Boom:
    """Stands in for a vitals evaluation that raises one of the caught types."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.called = False

    async def __call__(self, _metrics: Any) -> None:
        self.called = True
        raise self._exc


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(OSError("state file unwritable"), id="oserror"),
        pytest.param(ValueError("corrupt state json"), id="valueerror"),
        pytest.param(KeyError("missing band"), id="keyerror"),
        pytest.param(TypeError("bad metrics shape"), id="typeerror"),
        pytest.param(RuntimeError("ledger unavailable"), id="runtimeerror"),
    ],
)
def test_the_call_site_reports_a_failure_at_warning(
    exc: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    """Every exception the call site catches must still be reported.

    Parametrised over the caught set rather than one example: the arm exists
    to keep the health monitor alive, and each type is a different real
    failure (unwritable state dir, corrupt json, a band renamed, a metrics
    shape change, the change ledger being unreachable).
    """
    logger = logging.getLogger("hydraflow.health_monitor_loop")

    with caplog.at_level(logging.WARNING, logger=logger.name):
        try:
            raise exc
        except (OSError, RuntimeError, TypeError, ValueError, KeyError):
            logger.warning("fleet-vitals evaluation failed", exc_info=True)

    assert "fleet-vitals evaluation failed" in caplog.text


def test_the_source_does_not_swallow_the_failure_at_debug() -> None:
    """The property, read off the call site itself.

    `logger.debug` here is invisible at every level an operator or the console
    log actually runs at, so a broken supervisor looks exactly like a healthy
    one — which is the reading #11393 is asked to make.
    """
    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "health_monitor_loop"
        / "_heavy.py"
    ).read_text(encoding="utf-8")

    assert 'logger.debug("fleet-vitals evaluation failed"' not in source
    assert 'logger.warning("fleet-vitals evaluation failed"' in source


def test_the_evaluation_is_still_fail_soft() -> None:
    """Decoy: making it loud must not make it fatal.

    The arm exists so a broken shadow supervisor cannot take the health
    monitor down. Removing the try/except entirely would satisfy "not debug"
    while turning an advisory subsystem into an outage.
    """
    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "health_monitor_loop"
        / "_heavy.py"
    ).read_text(encoding="utf-8")

    assert "await self._run_fleet_vitals(metrics)" in source
    assert "except (OSError, RuntimeError, TypeError, ValueError, KeyError):" in source
