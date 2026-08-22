"""`GET /api/scheduling/status` — desired vs effective, and the shadow view (#11537).

#11537's fourth acceptance criterion is that operator status shows the desired
and effective scheduling mode and the hypothetical worker tree. A route that
returns the right shape but is never registered would satisfy that on paper and
not at all in a browser, so these tests go through the real dashboard router
rather than calling the handler functions directly.

The three sections are asserted separately because keeping them separate is the
point: *desired* is what the config says, *effective* is what the running
process built, and they are allowed to disagree — a director that fails its
startup boundary proof is detached for the run, and an operator must be able to
see that rather than infer it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.helpers import find_endpoint, make_dashboard_router


@pytest.fixture
def scheduling_status(config, event_bus, state, tmp_path):
    """The registered handler, resolved off the real router."""
    router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
    endpoint = find_endpoint(router, "/api/scheduling/status")
    assert endpoint is not None, "the scheduling status route is not registered"
    return endpoint


async def _body(endpoint) -> dict:
    return json.loads((await endpoint()).body)


class TestTheRouteIsReachable:
    async def test_the_route_is_registered_on_the_dashboard_router(
        self, scheduling_status
    ) -> None:
        # The fixture asserts registration; this names it as its own behaviour
        # so a lost `register()` call reads as a missing route rather than as
        # every other test in this file failing for an unrelated-looking reason.
        assert scheduling_status is not None

    async def test_it_answers_with_the_three_sections(self, scheduling_status) -> None:
        data = await _body(scheduling_status)

        assert set(data) >= {"desired", "effective", "shadow"}


class TestDesiredIsWhatTheConfigSays:
    async def test_it_names_the_active_preset(self, scheduling_status) -> None:
        data = await _body(scheduling_status)

        assert data["desired"]["preset"] == "Classic"

    async def test_it_reports_both_dials_separately(self, scheduling_status) -> None:
        # Two orthogonal fields behind one operator-facing preset name; the
        # backend must keep them apart or #11541 cannot move one alone.
        data = await _body(scheduling_status)

        assert (
            data["desired"]["scheduling_model"],
            data["desired"]["execution_runtime"],
        ) == ("phase_requeue", "stage_subprocess")

    async def test_it_offers_the_fable_preset_as_selectable(
        self, scheduling_status
    ) -> None:
        data = await _body(scheduling_status)

        names = [preset["name"] for preset in data["selectable_presets"]]

        assert "Fable director (shadow)" in names


#: One scalar per row, because four separate tests asserting
#: ``data[section][key] is expected`` are one parametrize waiting to happen —
#: which the suite-hygiene ratchet is right to say out loud. The reason each row
#: exists is kept with the row rather than lost in the collapse.
_STATUS_FLAGS = (
    pytest.param(
        "desired",
        "restart_required",
        True,
        # The orchestrator picks its pipeline loops once, at boot, so a live
        # badge on either dial would be a lie.
        id="both-dials-need-a-restart",
    ),
    pytest.param(
        "desired",
        "director_dispatch_armed",
        False,
        # Surfaced rather than omitted: an operator who selects the director
        # must be able to see that selecting it did not arm it.
        id="selecting-the-director-does-not-arm-dispatch",
    ),
    pytest.param(
        "effective",
        "running",
        False,
        # Effective is read off the live process, so with none running it must
        # say so rather than mirroring the config back.
        id="no-orchestrator-means-not-running",
    ),
    pytest.param(
        "shadow",
        "active",
        False,
        # An empty rollup and an absent director look identical in a summary of
        # zeroes; the operator needs to know which one they are looking at.
        id="no-director-means-the-shadow-view-is-inactive",
    ),
)


@pytest.mark.parametrize(("section", "key", "expected"), _STATUS_FLAGS)
async def test_a_status_flag_reports_the_classic_default(
    scheduling_status, section: str, key: str, expected: bool
) -> None:
    data = await _body(scheduling_status)

    assert data[section][key] is expected


class TestTheShadowViewIsInactiveUnderClassic:
    async def test_it_carries_no_observations(self, scheduling_status) -> None:
        data = await _body(scheduling_status)

        assert data["shadow"]["observations"] == []


class TestTheWorkerTreeReachesTheEndpoint:
    """A populated shadow log must be visible *through the route*.

    Proving the tree at the ``ShadowObservationLog`` level proves the recorder;
    criterion 4 is about what an operator can see, and the only thing that shows
    them is this response.
    """

    @staticmethod
    def _served(config, event_bus, state, tmp_path, log):
        """The route with a running orchestrator whose director holds *log*."""
        from types import SimpleNamespace

        orch = SimpleNamespace(
            _svc=SimpleNamespace(
                fable_director=SimpleNamespace(shadow_log=log),
                driver_manager=SimpleNamespace(has_observer=True, driven_issues={7}),
            )
        )
        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, get_orch=lambda: orch
        )
        return find_endpoint(router, "/api/scheduling/status")

    async def test_it_renders_the_hypothetical_worker_tree(
        self, config, event_bus, state, tmp_path
    ) -> None:
        from director_shadow_log import (
            ShadowAgreement,
            ShadowObservation,
            ShadowObservationLog,
        )

        log = ShadowObservationLog(tmp_path / "shadow.jsonl")
        log.record(
            ShadowObservation(
                recorded_at="2026-08-22T12:00:00+00:00",
                issue_number=7,
                driver_id="drv-7",
                epoch=0,
                phase="IMPLEMENT",
                live_outcome="committed",
                live_state="READY",
                agreement=ShadowAgreement.AGREED,
                command_kind="dispatch_workers",
                would_dispatch=({"role": "explorer", "dispatched": False},),
            )
        )
        endpoint = self._served(config, event_bus, state, tmp_path, log)

        data = json.loads((await endpoint()).body)

        assert data["shadow"]["observations"][0]["would_dispatch"][0]["role"] == (
            "explorer"
        )

    async def test_it_reports_no_worker_as_dispatched(
        self, config, event_bus, state, tmp_path
    ) -> None:
        from director_shadow_log import ShadowObservationLog

        log = ShadowObservationLog(tmp_path / "shadow.jsonl")
        endpoint = self._served(config, event_bus, state, tmp_path, log)

        data = json.loads((await endpoint()).body)

        assert data["shadow"]["summary"]["workers_dispatched"] == 0
