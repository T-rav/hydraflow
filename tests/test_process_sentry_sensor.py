"""The process-level exception sensor (ADR-0146 outbound half).

`build_observability_adapter` runs at the composition root, which the server
process reaches only after config load and factory boot — so a crash before
that point reported nothing, and the gateway, being its own process, reported
nothing ever. ADR-0147 made the gateway the path every LLM spawn takes, which
makes an unreported gateway crash a stopped factory with clean factory logs.

`install_process_sensor` is the entrypoint-level half: same SDK, same options,
started as early as a process can start it.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from observability import sentry_adapter
from observability.sentry_adapter import (
    init_sentry_sdk,
    install_process_sensor,
    sdk_component,
)


@pytest.fixture(autouse=True)
def _opt_back_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """`tests/conftest.py` disables the sensor suite-wide; this file must see it."""
    monkeypatch.delenv("HYDRAFLOW_SENTRY_DISABLED", raising=False)


@pytest.fixture
def _sdk(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stand in for the real SDK so no test can configure a live client."""
    fake = MagicMock()
    monkeypatch.setattr(sentry_adapter, "sentry_sdk", fake)
    return fake


class TestTheTargetIsResolvedFromTheEnvironment:
    """Rule 7: DSN from the environment, never from code."""

    def test_no_dsn_installs_nothing(self, _sdk: MagicMock) -> None:
        assert install_process_sensor("gateway", env={}) is False
        assert _sdk.init.called is False

    def test_a_dsn_installs_the_sensor(self, _sdk: MagicMock) -> None:
        installed = install_process_sensor(
            "gateway", env={"SENTRY_DSN": "https://k@example.invalid/1"}
        )

        assert installed is True
        assert _sdk.init.call_args.kwargs["dsn"] == "https://k@example.invalid/1"

    def test_a_whitespace_only_dsn_is_not_a_dsn(self, _sdk: MagicMock) -> None:
        assert install_process_sensor("gateway", env={"SENTRY_DSN": "   "}) is False


class TestTheKillSwitchStillWins:
    """Rule 2: the override direction is always OFF, even with a DSN present."""

    def test_disabled_beats_a_configured_dsn(self, _sdk: MagicMock) -> None:
        installed = install_process_sensor(
            "gateway",
            env={
                "SENTRY_DSN": "https://k@example.invalid/1",
                "HYDRAFLOW_SENTRY_DISABLED": "1",
            },
        )

        assert installed is False
        assert _sdk.init.called is False


class TestTheProcessIsInitialisedOnce:
    """`sentry_sdk.init` replaces the global client wholesale.

    The server installs the sensor at entrypoint and builds an injected
    adapter later in the same process. Without the guard the second call
    would discard the first client — and with it the component tag.
    """

    def test_a_second_install_does_not_reinitialise(self, _sdk: MagicMock) -> None:
        dsn = "https://k@example.invalid/1"
        assert install_process_sensor("server", env={"SENTRY_DSN": dsn}) is True

        assert install_process_sensor("server", env={"SENTRY_DSN": dsn}) is False
        assert _sdk.init.call_count == 1

    def test_the_first_component_is_the_one_that_sticks(self, _sdk: MagicMock) -> None:
        """A later adapter must not relabel events the entrypoint already owns."""
        install_process_sensor(
            "gateway", env={"SENTRY_DSN": "https://k@example.invalid/1"}
        )

        init_sentry_sdk("https://k@example.invalid/1", component="factory")

        assert sdk_component() == "gateway"


class TestEventsCarryTheirOrigin:
    """One Bugsink project receives from several processes; triage needs the source."""

    def test_the_component_is_tagged_on_the_global_scope(self, _sdk: MagicMock) -> None:
        """Global, not current: the tag must survive every scope push.

        The loops and the ASGI middleware both push scopes; a tag set on the
        current scope would be gone by the time an event was captured.
        """
        init_sentry_sdk("https://k@example.invalid/1", component="gateway")

        _sdk.get_global_scope.return_value.set_tag.assert_called_once_with(
            "hydraflow.component", "gateway"
        )


class TestOnlyBugsBecomeIssues:
    """Sentry's logging integration promotes EVERY `logger.error` to an event.

    49 of this repo's error-level call sites carry no exception at all. Those
    arrive with no stack trace and no exception type, so Bugsink groups them on
    message text and triage gets a sentence it cannot act on — rule 9 would
    auto-close it as a transient after it had already taken a slot.
    """

    def _log_record_hint(self) -> dict[str, object]:
        return {
            "log_record": logging.LogRecord(
                "n", logging.ERROR, "p", 1, "operational", None, None
            )
        }

    def test_a_logged_line_with_no_exception_is_dropped(self) -> None:
        assert (
            sentry_adapter._bugs_only({"level": "error"}, self._log_record_hint())
            is None
        )

    def test_a_logged_line_with_an_exception_is_kept(self) -> None:
        """The broad-except shape: `logger.error(..., exc_info=True)`."""
        hint = self._log_record_hint()
        hint["exc_info"] = (KeyError, KeyError("k"), None)

        assert sentry_adapter._bugs_only({"level": "error"}, hint) is not None

    def test_an_event_carrying_an_exception_is_kept(self) -> None:
        event = {"exception": {"values": [{"type": "TypeError"}]}}

        assert sentry_adapter._bugs_only(event, {}) is not None

    def test_an_explicit_capture_message_is_kept(self) -> None:
        """Decoy: the filter targets INCIDENTAL promotion, not every message.

        A call site that reached for `capture_message` said what it meant. A
        filter keyed on "has no exception" rather than on `log_record` would
        silently swallow those too.
        """
        assert sentry_adapter._bugs_only({"level": "error"}, {}) is not None


class TestABrokenSensorDoesNotStopBoot:
    """Rule 4: an unreachable endpoint degrades; the process keeps running."""

    def test_an_init_that_raises_is_swallowed(self, _sdk: MagicMock) -> None:
        _sdk.init.side_effect = RuntimeError("no route to host")

        installed = install_process_sensor(
            "gateway", env={"SENTRY_DSN": "https://k@example.invalid/1"}
        )

        assert installed is False


class TestTheEntrypointsInstallIt:
    """The wiring itself, at both processes that own one."""

    def test_the_gateway_installs_the_sensor_before_serving(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import hydraflow_gateway.__main__ as gateway_main

        installed: list[str] = []

        def _record(component: str) -> None:
            installed.append(component)

        monkeypatch.setattr(sentry_adapter, "install_process_sensor", _record)
        monkeypatch.setattr(gateway_main.uvicorn, "run", lambda *a, **k: None)

        gateway_main.main()

        assert installed == ["gateway"]

    def test_the_server_installs_the_sensor_before_loading_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Before config load, so a boot failure is reported rather than silent."""
        import server

        order: list[str] = []
        monkeypatch.setattr(
            sentry_adapter,
            "install_process_sensor",
            lambda component: order.append(f"sensor:{component}"),
        )
        monkeypatch.setattr(
            server, "load_runtime_config", lambda: order.append("config") or MagicMock()
        )
        monkeypatch.setattr(server, "setup_logging", lambda **k: None)
        monkeypatch.setattr(server.asyncio, "run", lambda coro: coro.close())

        server.main([])

        assert order == ["sensor:server", "config"]
