"""Tests for the low-noise Honeycomb SLO / burn-alert ingestion loop."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tests.helpers import ConfigFactory


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class _FakeHoneycombClient:
    """Async-context-manager fake returning canned JSON per URL prefix.

    ``routes`` maps a URL substring → payload. A new instance is yielded per
    ``__aenter__`` so the loop's per-call ``async with`` works, but all share
    the same backing ``routes`` dict so a test can mutate state across polls.
    """

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    async def __aenter__(self) -> _FakeHoneycombClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get(self, url: str, *, headers: dict | None = None) -> _FakeResponse:
        self.calls.append(url)
        for prefix, payload in self.routes.items():
            if prefix in url:
                return _FakeResponse(payload)
        return _FakeResponse([])


def _make_deps():
    from base_background_loop import LoopDeps

    deps = MagicMock(spec=LoopDeps)
    deps.event_bus = AsyncMock()
    deps.stop_event = MagicMock()
    deps.status_cb = MagicMock()
    deps.enabled_cb = MagicMock(return_value=True)
    deps.sleep_fn = AsyncMock()
    deps.interval_cb = None
    return deps


def _slo(slo_id: str = "slo-1", budget_remaining: float = 0.0) -> dict:
    return {
        "id": slo_id,
        "name": "checkout availability",
        "budget_remaining": budget_remaining,
        "target_per_million": 999_000,
    }


def _burn_alert(slo_id: str = "slo-1", state: str = "TRIGGERED") -> dict:
    return {"id": "ba-1", "alert_type": state, "slo": {"id": slo_id}, "name": "burn"}


def _make_loop(
    tmp_path: Path,
    routes: dict[str, Any],
    *,
    enabled: bool = True,
    key: str = "hcaik_test",
    **overrides: Any,
):
    from config import Credentials
    from honeycomb_loop import HoneycombIngestLoop

    config = ConfigFactory.create(repo_root=tmp_path)
    object.__setattr__(config, "honeycomb_ingest_loop_enabled", enabled)
    object.__setattr__(config, "honeycomb_datasets", "prod")
    object.__setattr__(config, "honeycomb_slo_budget_threshold_pct", 0.0)
    object.__setattr__(config, "honeycomb_min_sustained_polls", 2)
    object.__setattr__(config, "honeycomb_signal_cooldown_hours", 24)
    object.__setattr__(config, "honeycomb_auto_close_enabled", True)
    for field, value in overrides.items():
        object.__setattr__(config, field, value)

    creds = Credentials(honeycomb_mgmt_api_key=key)
    deps = _make_deps()
    prs = MagicMock()
    prs.create_issue = AsyncMock(return_value=4242)
    prs.find_existing_issue = AsyncMock(return_value=0)
    prs.post_comment = AsyncMock()
    prs.close_issue = AsyncMock()

    shared = _FakeHoneycombClient(routes)
    loop = HoneycombIngestLoop(
        config=config,
        prs=prs,
        deps=deps,
        credentials=creds,
        http_client_factory=lambda: shared,
        state_path=tmp_path / "hc_state.json",
    )
    return loop, prs


class TestDisabledByDefault:
    async def test_noop_when_flag_disabled(self, tmp_path: Path) -> None:
        loop, prs = _make_loop(tmp_path, {"/1/slos/": [_slo()]}, enabled=False)
        result = await loop._do_work()
        assert result == {"status": "disabled"}
        prs.create_issue.assert_not_called()

    async def test_noop_when_no_api_key(self, tmp_path: Path) -> None:
        loop, prs = _make_loop(tmp_path, {"/1/slos/": [_slo()]}, key="")
        result = await loop._do_work()
        assert result == {"status": "disabled"}
        prs.create_issue.assert_not_called()

    async def test_noop_when_kill_switch_off(self, tmp_path: Path) -> None:
        loop, prs = _make_loop(tmp_path, {"/1/slos/": [_slo()]})
        loop._enabled_cb = MagicMock(return_value=False)
        result = await loop._do_work()
        assert result == {"status": "disabled"}
        prs.create_issue.assert_not_called()


class TestSustainedPollGate:
    async def test_first_breach_does_not_file(self, tmp_path: Path) -> None:
        routes = {"/1/slos/": [_slo(budget_remaining=0.0)], "/1/burn_alerts/": []}
        loop, prs = _make_loop(tmp_path, routes)
        result = await loop._do_work()
        assert result["issues_created"] == 0
        prs.create_issue.assert_not_called()

    async def test_files_on_nth_consecutive_breach(self, tmp_path: Path) -> None:
        routes = {"/1/slos/": [_slo(budget_remaining=0.0)], "/1/burn_alerts/": []}
        loop, prs = _make_loop(tmp_path, routes)  # min_sustained_polls=2
        await loop._do_work()  # poll 1: observe only
        prs.create_issue.assert_not_called()
        result = await loop._do_work()  # poll 2: sustained -> file
        assert result["issues_created"] == 1
        prs.create_issue.assert_called_once()
        title, body = (
            prs.create_issue.call_args.args[0],
            prs.create_issue.call_args.args[1],
        )
        assert "Honeycomb" in title
        assert "<!-- [honeycomb:slo-1] -->" in body

    async def test_counter_resets_when_signal_clears(self, tmp_path: Path) -> None:
        routes = {"/1/slos/": [_slo(budget_remaining=0.0)], "/1/burn_alerts/": []}
        loop, prs = _make_loop(tmp_path, routes)
        await loop._do_work()  # breach poll 1
        # Signal recovers before the gate is met.
        routes["/1/slos/"] = [_slo(budget_remaining=0.5)]
        await loop._do_work()  # healthy -> counter reset
        # Breach returns; one breach is NOT enough since the counter reset.
        routes["/1/slos/"] = [_slo(budget_remaining=0.0)]
        result = await loop._do_work()
        assert result["issues_created"] == 0
        prs.create_issue.assert_not_called()


class TestBudgetThreshold:
    async def test_budget_above_threshold_never_files(self, tmp_path: Path) -> None:
        routes = {"/1/slos/": [_slo(budget_remaining=0.5)], "/1/burn_alerts/": []}
        loop, prs = _make_loop(tmp_path, routes)
        await loop._do_work()
        await loop._do_work()
        await loop._do_work()
        prs.create_issue.assert_not_called()

    async def test_custom_threshold_files(self, tmp_path: Path) -> None:
        # 10% remaining, threshold 20% -> breaching.
        routes = {"/1/slos/": [_slo(budget_remaining=0.10)], "/1/burn_alerts/": []}
        loop, prs = _make_loop(
            tmp_path, routes, honeycomb_slo_budget_threshold_pct=20.0
        )
        await loop._do_work()
        result = await loop._do_work()
        assert result["issues_created"] == 1


class TestBurnAlertAnding:
    async def test_burn_alert_requires_budget_below_threshold(
        self, tmp_path: Path
    ) -> None:
        # Burn alert firing but budget healthy -> NOT breaching (AND-ed).
        routes = {
            "/1/slos/": [_slo(budget_remaining=0.9)],
            "/1/burn_alerts/": [_burn_alert()],
        }
        loop, prs = _make_loop(tmp_path, routes)
        await loop._do_work()
        await loop._do_work()
        prs.create_issue.assert_not_called()


class TestCrossSignalDedup:
    async def test_slo_and_its_burn_alert_emit_one_issue(self, tmp_path: Path) -> None:
        routes = {
            "/1/slos/": [_slo(slo_id="slo-1", budget_remaining=0.0)],
            "/1/burn_alerts/": [_burn_alert(slo_id="slo-1")],
        }
        loop, prs = _make_loop(tmp_path, routes)
        await loop._do_work()
        result = await loop._do_work()
        assert result["issues_created"] == 1
        assert prs.create_issue.call_count == 1


class TestCooldown:
    async def test_no_refile_within_cooldown(self, tmp_path: Path) -> None:
        routes = {"/1/slos/": [_slo(budget_remaining=0.0)], "/1/burn_alerts/": []}
        loop, prs = _make_loop(tmp_path, routes)
        await loop._do_work()
        await loop._do_work()  # files
        assert prs.create_issue.call_count == 1
        # Simulate recovery (auto-close clears issue_number) then immediate
        # re-breach: the cooldown stamp must suppress the re-file.
        routes["/1/slos/"] = [_slo(budget_remaining=0.5)]
        await loop._do_work()  # recovered -> auto-close + cooldown stamp
        routes["/1/slos/"] = [_slo(budget_remaining=0.0)]
        await loop._do_work()
        await loop._do_work()
        # Still only the original create; cooldown blocked the second file.
        assert prs.create_issue.call_count == 1


class TestAutoClose:
    async def test_closes_issue_on_recovery(self, tmp_path: Path) -> None:
        routes = {"/1/slos/": [_slo(budget_remaining=0.0)], "/1/burn_alerts/": []}
        loop, prs = _make_loop(tmp_path, routes)
        await loop._do_work()
        await loop._do_work()  # files #4242
        prs.create_issue.assert_called_once()
        routes["/1/slos/"] = [_slo(budget_remaining=0.5)]  # recovered
        result = await loop._do_work()
        assert result["issues_closed"] == 1
        prs.post_comment.assert_awaited_once()
        prs.close_issue.assert_awaited_once_with(4242)

    async def test_no_close_when_disabled(self, tmp_path: Path) -> None:
        routes = {"/1/slos/": [_slo(budget_remaining=0.0)], "/1/burn_alerts/": []}
        loop, prs = _make_loop(tmp_path, routes, honeycomb_auto_close_enabled=False)
        await loop._do_work()
        await loop._do_work()  # files
        routes["/1/slos/"] = [_slo(budget_remaining=0.5)]  # recovered
        await loop._do_work()
        prs.close_issue.assert_not_called()

    async def test_close_when_signal_vanishes(self, tmp_path: Path) -> None:
        routes = {"/1/slos/": [_slo(budget_remaining=0.0)], "/1/burn_alerts/": []}
        loop, prs = _make_loop(tmp_path, routes)
        await loop._do_work()
        await loop._do_work()  # files
        routes["/1/slos/"] = []  # SLO disappears entirely
        result = await loop._do_work()
        assert result["issues_closed"] == 1
        prs.close_issue.assert_awaited_once_with(4242)


class TestTriggerIngestOptIn:
    async def test_orphan_burn_alert_ignored_by_default(self, tmp_path: Path) -> None:
        # Burn alert with no parent SLO -> trigger-only; default off.
        routes = {
            "/1/slos/": [],
            "/1/burn_alerts/": [{"id": "ba-9", "alert_type": "TRIGGERED", "name": "x"}],
        }
        loop, prs = _make_loop(tmp_path, routes)
        await loop._do_work()
        await loop._do_work()
        await loop._do_work()
        prs.create_issue.assert_not_called()

    async def test_orphan_burn_alert_files_when_enabled(self, tmp_path: Path) -> None:
        routes = {
            "/1/slos/": [],
            "/1/burn_alerts/": [{"id": "ba-9", "alert_type": "TRIGGERED", "name": "x"}],
        }
        loop, prs = _make_loop(
            tmp_path,
            routes,
            honeycomb_trigger_ingest_enabled=True,
            honeycomb_trigger_sustained_polls=2,
        )
        await loop._do_work()
        result = await loop._do_work()
        assert result["issues_created"] == 1


class TestPerDatasetErrorIsolation:
    async def test_one_bad_dataset_does_not_kill_tick(self, tmp_path: Path) -> None:
        import httpx

        from config import Credentials
        from honeycomb_loop import HoneycombIngestLoop

        config = ConfigFactory.create(repo_root=tmp_path)
        object.__setattr__(config, "honeycomb_ingest_loop_enabled", True)
        object.__setattr__(config, "honeycomb_datasets", "bad,good")
        object.__setattr__(config, "honeycomb_min_sustained_polls", 1)

        prs = MagicMock()
        prs.create_issue = AsyncMock(return_value=11)
        prs.find_existing_issue = AsyncMock(return_value=0)
        prs.post_comment = AsyncMock()
        prs.close_issue = AsyncMock()

        class _PerDatasetClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return None

            async def get(self, url, *, headers=None):
                if "/bad" in url:
                    raise httpx.ConnectError("boom")
                if "/1/slos/good" in url:
                    return _FakeResponse(
                        [_slo(slo_id="good-slo", budget_remaining=0.0)]
                    )
                return _FakeResponse([])

        loop = HoneycombIngestLoop(
            config=config,
            prs=prs,
            deps=_make_deps(),
            credentials=Credentials(honeycomb_mgmt_api_key="k"),
            http_client_factory=_PerDatasetClient,
            state_path=tmp_path / "s.json",
        )
        result = await loop._do_work()
        # 'bad' raised and was skipped; 'good' filed (min_sustained_polls=1).
        assert result["skipped"] >= 1
        assert result["issues_created"] == 1


class TestCreationAttemptParking:
    async def test_parks_after_max_attempts(self, tmp_path: Path) -> None:
        routes = {"/1/slos/": [_slo(budget_remaining=0.0)], "/1/burn_alerts/": []}
        loop, prs = _make_loop(
            tmp_path,
            routes,
            honeycomb_min_sustained_polls=1,
            honeycomb_max_creation_attempts=2,
        )
        prs.create_issue = AsyncMock(side_effect=RuntimeError("gh down"))
        await loop._do_work()  # attempt 1
        await loop._do_work()  # attempt 2 -> parked
        before = prs.create_issue.call_count
        await loop._do_work()  # parked: no more attempts
        assert prs.create_issue.call_count == before
