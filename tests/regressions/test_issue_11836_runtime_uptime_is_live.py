"""Regression (#11836): `/api/runtimes` must report a live uptime.

Measured 2026-08-31 on a healthy boot — three samples 15s apart, a runtime that
had been up for minutes and had `Starting runtime for` exactly once, zero
`exited with exception`, zero `Traceback`:

    running=True uptime=0.0
    running=True uptime=0.0
    running=True uptime=0.0

Cause: `RepoRuntimeInfo.uptime_seconds` defaults to 0.0 in the model and
**neither** construction site in `_state_routes.py` ever passed it. The field
was unwired, not stale.

Why it matters beyond cosmetics: this is the field an operator uses to tell a
*running* factory from a *crashlooping* one, and it is the documented remedy for
a known blind spot — `status: idle` is returned identically by a healthy idle
factory and by one dying and restarting every ~25s (#11786). The prescribed
workaround was "trust the runtime, not the status", but a runtime whose liveness
counter never advances cannot distinguish them either. A restart is visible only
because uptime RESETS; pinned at 0.0, both cases are byte-identical.

Note on the assertion shape: `assert uptime >= 0` passes against the broken
behaviour. Every positive test here asserts strictly greater than zero after a
non-zero interval.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from orchestrator_stats import OrchestratorStatsMixin


class _Session:
    def __init__(self, started_at: str) -> None:
        self.started_at = started_at
        self.id = "session-1"


class _Probe(OrchestratorStatsMixin):
    """Minimal carrier: the mixin only needs ``_current_session`` for this."""

    def __init__(self, session: _Session | None) -> None:
        self._current_session = session


def _iso(seconds_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()


def test_uptime_is_positive_for_a_session_started_in_the_past() -> None:
    probe = _Probe(_Session(_iso(120)))
    assert probe.current_session_uptime_seconds > 0


def test_uptime_reflects_the_elapsed_interval() -> None:
    """Strictly-positive is not enough on its own — pin the magnitude too.

    A stub returning a constant 1.0 would satisfy the test above.
    """
    probe = _Probe(_Session(_iso(300)))
    assert 290 < probe.current_session_uptime_seconds < 310


def test_uptime_grows_between_two_sessions_of_different_age() -> None:
    younger = _Probe(_Session(_iso(60))).current_session_uptime_seconds
    older = _Probe(_Session(_iso(600))).current_session_uptime_seconds
    assert older > younger


def test_no_session_is_zero() -> None:
    assert _Probe(None).current_session_uptime_seconds == 0.0


def test_empty_started_at_is_zero() -> None:
    assert _Probe(_Session("")).current_session_uptime_seconds == 0.0


@pytest.mark.parametrize("bad", ["not-a-date", "2026-13-45T99:99:99", "   "])
def test_unparseable_started_at_is_zero_not_an_exception(bad: str) -> None:
    """The route serialises this on every poll; a raise would 500 the dashboard."""
    assert _Probe(_Session(bad)).current_session_uptime_seconds == 0.0


def _runtime_mock(*, running: bool, uptime: float) -> MagicMock:
    rt = MagicMock()
    rt.slug = "org-repo"
    rt.config.repo = "org/repo"
    rt.config.repo_provider = "claude"
    rt.running = running
    rt.last_error = None
    rt.orchestrator.current_session_id = "sess-1"
    # Pin an explicit float. A bare MagicMock would be ACCEPTED here: Pydantic
    # coerces it via ``__float__`` to 1.0 rather than raising, so a route test
    # left on the default mock would assert `> 0` and pass on the mock's own
    # coercion instead of on the value the route actually forwarded.
    rt.orchestrator.current_session_uptime_seconds = uptime
    return rt


async def _list_runtimes(rt: MagicMock, config, event_bus, state, tmp_path) -> dict:
    from tests.helpers import find_endpoint, make_dashboard_router

    registry = MagicMock()
    registry.all = [rt]
    router, _ = make_dashboard_router(
        config, event_bus, state, tmp_path, registry=registry
    )
    resp = await find_endpoint(router, "/api/runtimes")()
    return json.loads(resp.body)


@pytest.mark.asyncio
async def test_route_forwards_the_uptime_for_a_running_runtime(
    config, event_bus, state, tmp_path
) -> None:
    """Drives the real endpoint — the defect was in the ROUTE, not the property.

    The property can be perfect while the route never passes it, which is
    exactly what shipped: both construction sites omitted the argument and the
    model's 0.0 default answered forever. A test that builds RepoRuntimeInfo by
    hand cannot see that, and the first version of this file did precisely that
    — it stayed green when the wiring was reverted.

    The asserted value is exact, not `> 0`: a bare MagicMock orchestrator makes
    the field 1.0 through Pydantic's float coercion, so `> 0` would pass without
    the route reading this property at all.
    """
    data = await _list_runtimes(
        _runtime_mock(running=True, uptime=1234.5), config, event_bus, state, tmp_path
    )
    row = next(r for r in data["runtimes"] if r["slug"] == "org-repo")
    assert row["uptime_seconds"] == 1234.5


@pytest.mark.asyncio
async def test_route_reports_zero_for_a_stopped_runtime(
    config, event_bus, state, tmp_path
) -> None:
    """Stopped reports 0.0 truthfully, mirroring how session_id becomes None."""
    data = await _list_runtimes(
        _runtime_mock(running=False, uptime=999.0), config, event_bus, state, tmp_path
    )
    row = next(r for r in data["runtimes"] if r["slug"] == "org-repo")
    assert row["uptime_seconds"] == 0.0
