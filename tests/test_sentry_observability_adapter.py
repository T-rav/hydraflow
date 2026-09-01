"""Sentry as the error backend (ADR-0146) — errors only, DSN is the switch.

ADR-0118 removed Sentry by name and pointed at New Relic. ADR-0146 supersedes
that direction: Sentry ingests errors. Scope is deliberately narrow —
`set_measurement` stays unimplemented and tracing is untouched, because a
transport that quietly began sampling transactions would re-instrument the
loops, which is the thing ADR-0118 objected to and this ADR does not reverse.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from config import Credentials
from observability.noop_adapter import NoOpObservabilityAdapter
from observability.sentry_adapter import (
    SentryObservabilityAdapter,
    build_observability_adapter,
)


@pytest.fixture(autouse=True)
def _opt_back_in(monkeypatch) -> None:
    """Clear the suite-wide kill switch so these tests can exercise the builder.

    ``tests/conftest.py`` sets ``HYDRAFLOW_SENTRY_DISABLED=1`` at import time so
    no fixture noise can ever reach a real project. That is exactly right for
    the suite and fatal for this file, which is the one place that must watch
    the builder return a live adapter — without this every assertion below would
    pass against the no-op and prove nothing. The opt-back-in is per-test and
    monkeypatched, so it cannot leak into another module.
    """
    monkeypatch.delenv("HYDRAFLOW_SENTRY_DISABLED", raising=False)


class TestTheKillSwitch:
    """``HYDRAFLOW_SENTRY_DISABLED`` overrides a present DSN, always toward OFF.

    ADR-0118 deleted ``_init_sentry``, the only code that read this flag, and
    left conftest plus three regressions (#10876, #11580, #11589) defending it.
    These are what make it real again.
    """

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("1", id="one"),
            pytest.param("true", id="true"),
            pytest.param("TRUE", id="upper"),
            pytest.param("yes", id="yes"),
        ],
    )
    def test_the_flag_beats_a_present_dsn(self, monkeypatch, value: str) -> None:
        monkeypatch.setattr("sentry_sdk.init", MagicMock(), raising=True)
        monkeypatch.setenv("HYDRAFLOW_SENTRY_DISABLED", value)

        adapter = build_observability_adapter(
            Credentials(sentry_dsn="https://k@o.ingest.sentry.io/1")
        )

        assert isinstance(adapter, NoOpObservabilityAdapter)

    def test_init_is_never_called_when_disabled(self, monkeypatch) -> None:
        """Not just the return type — the SDK must not be touched at all."""
        init = MagicMock()
        monkeypatch.setattr("sentry_sdk.init", init, raising=True)
        monkeypatch.setenv("HYDRAFLOW_SENTRY_DISABLED", "1")

        build_observability_adapter(
            Credentials(sentry_dsn="https://k@o.ingest.sentry.io/1")
        )

        init.assert_not_called()

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("", id="empty"),
            pytest.param("0", id="zero"),
            pytest.param("false", id="false"),
            pytest.param("no", id="no"),
        ],
    )
    def test_an_off_value_does_not_disable(self, monkeypatch, value: str) -> None:
        """The decoy: a flag that disabled on any value would break `=0`."""
        monkeypatch.setattr("sentry_sdk.init", MagicMock(), raising=True)
        monkeypatch.setenv("HYDRAFLOW_SENTRY_DISABLED", value)

        adapter = build_observability_adapter(
            Credentials(sentry_dsn="https://k@o.ingest.sentry.io/1")
        )

        assert isinstance(adapter, SentryObservabilityAdapter)


class TestTheDsnIsTheSwitch:
    def test_no_dsn_gets_the_no_op(self) -> None:
        """Tests, CI and the air-gapped sandbox carry no DSN.

        The DSN is the primary switch; HYDRAFLOW_SENTRY_DISABLED overrides it
        toward OFF (see TestTheKillSwitch), so the two cannot disagree about
        anything that matters, and a test run cannot page a human.
        """
        adapter = build_observability_adapter(Credentials())

        assert isinstance(adapter, NoOpObservabilityAdapter)

    @pytest.mark.parametrize(
        "dsn",
        [pytest.param("", id="empty"), pytest.param("   ", id="whitespace")],
    )
    def test_a_blank_dsn_is_no_dsn(self, dsn: str) -> None:
        adapter = build_observability_adapter(Credentials(sentry_dsn=dsn))

        assert isinstance(adapter, NoOpObservabilityAdapter)

    def test_a_dsn_gets_the_sentry_adapter(self, monkeypatch) -> None:
        monkeypatch.setattr("sentry_sdk.init", MagicMock(), raising=True)
        adapter = build_observability_adapter(
            Credentials(sentry_dsn="https://k@o.ingest.sentry.io/1")
        )

        assert isinstance(adapter, SentryObservabilityAdapter)

    def test_a_broken_init_falls_back_instead_of_failing_boot(
        self, monkeypatch
    ) -> None:
        # An unreachable or malformed reporter must not stop the factory
        # starting. Observability that can fail the work it observes has turned
        # a diagnostic into an outage.
        monkeypatch.setattr(
            "sentry_sdk.init", MagicMock(side_effect=RuntimeError("bad dsn"))
        )

        adapter = build_observability_adapter(Credentials(sentry_dsn="nonsense"))

        assert isinstance(adapter, NoOpObservabilityAdapter)


class TestErrorsOnly:
    @staticmethod
    def _adapter(monkeypatch) -> tuple[SentryObservabilityAdapter, MagicMock]:
        sdk = MagicMock()
        monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", sdk)
        return SentryObservabilityAdapter("https://k@o.ingest.sentry.io/1"), sdk

    def test_an_exception_reaches_sentry(self, monkeypatch) -> None:
        adapter, sdk = self._adapter(monkeypatch)
        exc = ValueError("boom")

        adapter.capture_exception(exc)

        sdk.capture_exception.assert_called_once_with(exc)

    def test_a_message_reaches_sentry(self, monkeypatch) -> None:
        adapter, sdk = self._adapter(monkeypatch)

        adapter.capture_message("hello", level="warning")

        sdk.capture_message.assert_called_once_with("hello", level="warning")

    @pytest.mark.parametrize(
        ("given", "sent"),
        [
            pytest.param("warning", "warning", id="known-level-passes-through"),
            pytest.param("WARN", "info", id="unknown-level-falls-back"),
            pytest.param("", "info", id="empty-falls-back"),
        ],
    )
    def test_an_unknown_level_does_not_reach_the_wire(
        self, monkeypatch, given: str, sent: str
    ) -> None:
        """`ObservabilityPort` types `level` as a plain `str`.

        Casting it straight through would let a typo arrive at Sentry as an
        unknown level, which is the quiet kind of wrong a cast hides.
        """
        adapter, sdk = self._adapter(monkeypatch)

        adapter.capture_message("m", level=given)

        assert sdk.capture_message.call_args.kwargs["level"] == sent

    def test_a_measurement_does_not(self, monkeypatch) -> None:
        """Metrics are unimplemented, not routed elsewhere.

        ADR-0118 pointed them at New Relic; ADR-0146 drops that direction
        without replacing it, so this is honestly a no-op rather than pending a
        named backend.
        """
        adapter, sdk = self._adapter(monkeypatch)
        sdk.reset_mock()  # discard the constructor's init() call

        adapter.set_measurement("latency", 1.0, "second")

        assert sdk.method_calls == []

    def test_tracing_is_initialised_off(self, monkeypatch) -> None:
        # The decoy that matters. A non-zero sample rate would re-instrument
        # the phase blocks by the back door — spans stay OTel's concern.
        sdk = MagicMock()
        monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", sdk)

        SentryObservabilityAdapter("https://k@o.ingest.sentry.io/1")

        assert sdk.init.call_args.kwargs["traces_sample_rate"] == 0.0

    def test_pii_is_not_sent_by_default(self, monkeypatch) -> None:
        # Prompts and transcripts routinely carry issue and PR text; shipping
        # local variables to a third party as a side effect of an error is not
        # something an error reporter should decide on its own.
        sdk = MagicMock()
        monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", sdk)

        SentryObservabilityAdapter("https://k@o.ingest.sentry.io/1")

        assert sdk.init.call_args.kwargs["send_default_pii"] is False


class TestReportingNeverRaises:
    @pytest.mark.parametrize(
        ("method", "args"),
        [
            pytest.param("capture_exception", (ValueError("x"),), id="exception"),
            pytest.param("capture_message", ("m",), id="message"),
            pytest.param("breadcrumb", ("cat", "msg"), id="breadcrumb"),
        ],
    )
    def test_a_transport_failure_is_swallowed(
        self, monkeypatch, method: str, args: tuple
    ) -> None:
        """A loop that dies because its reporter was unreachable is worse than
        one that loses a report."""
        sdk = MagicMock()
        for name in ("capture_exception", "capture_message", "add_breadcrumb"):
            getattr(sdk, name).side_effect = RuntimeError("network down")
        monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", sdk)
        adapter = SentryObservabilityAdapter("https://k@o.ingest.sentry.io/1")

        getattr(adapter, method)(*args)  # must not raise

    def test_a_failed_flush_reports_false_rather_than_raising(
        self, monkeypatch
    ) -> None:
        sdk = MagicMock()
        sdk.flush.side_effect = RuntimeError("network down")
        monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", sdk)
        adapter = SentryObservabilityAdapter("https://k@o.ingest.sentry.io/1")

        assert adapter.flush() is False


class TestTheCredentialIsDeclared:
    def test_the_dsn_env_key_is_in_the_declared_surface(self) -> None:
        """#10885: every credential env var is enumerable, not hand-listed."""
        from config import CREDENTIAL_ENV_KEYS

        assert "SENTRY_DSN" in CREDENTIAL_ENV_KEYS

    def test_the_dsn_is_read_from_dotenv_not_only_the_shell(
        self, tmp_path, monkeypatch
    ) -> None:
        """The deployment keeps it in `.env` and does not export it.

        An os.environ-only read would leave the adapter permanently inert while
        looking configured — the failure this whole session has been about.
        """
        from config import HydraFlowConfig, build_credentials

        monkeypatch.delenv("SENTRY_DSN", raising=False)
        (tmp_path / ".env").write_text(
            "SENTRY_DSN=https://k@o.ingest.sentry.io/9\n", encoding="utf-8"
        )
        config = HydraFlowConfig(repo_root=tmp_path)

        assert build_credentials(config).sentry_dsn.endswith("/9")
