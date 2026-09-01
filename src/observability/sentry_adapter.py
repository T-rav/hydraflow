"""Sentry-SDK implementation of ``ObservabilityPort`` — errors only.

The SDK is Sentry's; the TARGET is whatever the DSN names. Bugsink speaks the
same ingest protocol and is the house default (ADR-0146), so this one adapter
serves both — pointing a repo at sentry.io instead is a DSN change, not a code
change. Named after the library it uses rather than the backend it happens to
reach, because the backend is configuration.

This is the outbound half of the exception sensor
(``docs/standards/exception_sensor/``). The inbound half — errors becoming
GitHub issues the pipeline can triage — is the backend's own tracker
integration, not code here.

**Errors only, deliberately.** ``capture_exception`` / ``capture_message`` /
``breadcrumb`` reach Sentry; ``set_measurement`` stays a no-op. Tracing is out
of scope entirely — ``phase_utils._sentry_transaction`` remains the no-op it is
today, and the intended direction for spans is OTel rather than Sentry. This
adapter therefore initialises with tracing OFF: a transport that silently began
sampling transactions would re-instrument the loops, which is the specific thing
ADR-0118 objected to.

**The DSN is the switch.** ``build_observability_adapter`` returns this adapter
only when a DSN is configured, and the no-op otherwise. Tests, CI and the
air-gapped sandbox carry no DSN, so they fall back automatically — there is no
flag to forget, and no way for a test run to page a human. That matters more
than convenience here: the sandbox is network-isolated, so an adapter that
tried to send would hang against the egress block rather than fail fast.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from config import Credentials
    from ports import ObservabilityPort

logger = logging.getLogger("hydraflow.observability.sentry")


#: The levels Sentry accepts. `ObservabilityPort` types `level` as a plain
#: `str`, so this is the boundary where an arbitrary caller string becomes one
#: of them — validated rather than cast, because a typo silently reaching the
#: wire as an unknown level is the kind of quiet wrongness a cast would hide.
_SENTRY_LEVELS: frozenset[str] = frozenset(
    {"fatal", "critical", "error", "warning", "info", "debug"}
)


def _sentry_level(level: str) -> Any:
    """Coerce a port-level string to something Sentry recognises."""
    return level if level in _SENTRY_LEVELS else "info"


class SentryObservabilityAdapter:
    """``ObservabilityPort`` backed by Sentry, for errors.

    Constructed once at the composition root. Every method swallows transport
    failures: observability must never be able to fail the work it observes —
    a loop that dies because its error reporter was unreachable has turned a
    diagnostic into an outage.
    """

    #: Distinguishes the real (production) adapter from a test Fake, matching
    #: ``NoOpObservabilityAdapter``'s marker so callers can tell them apart.
    _is_fake_adapter: bool = False

    def __init__(self, dsn: str) -> None:
        import sentry_sdk  # noqa: PLC0415

        self._sdk = sentry_sdk
        sentry_sdk.init(
            dsn=dsn,
            # Tracing OFF: spans are not Sentry's job here (ADR-0146). A
            # non-zero rate would re-instrument the phase blocks by the back
            # door, which ADR-0118 objected to and this ADR does not reverse.
            traces_sample_rate=0.0,
            # The factory's prompts and transcripts routinely contain issue and
            # PR text. Sending request bodies and local variables by default
            # would ship that to a third party as a side effect of an error.
            send_default_pii=False,
        )

    def capture_exception(self, exc: BaseException) -> None:
        try:
            self._sdk.capture_exception(exc)
        except Exception:  # noqa: BLE001 - reporting must not raise
            logger.debug("sentry capture_exception failed", exc_info=True)

    def capture_message(self, message: str, *, level: str = "info") -> None:
        try:
            self._sdk.capture_message(message, level=_sentry_level(level))
        except Exception:  # noqa: BLE001 - reporting must not raise
            logger.debug("sentry capture_message failed", exc_info=True)

    def breadcrumb(self, category: str, message: str, **data: object) -> None:
        try:
            self._sdk.add_breadcrumb(
                category=category, message=message, data=dict(data)
            )
        except Exception:  # noqa: BLE001 - reporting must not raise
            logger.debug("sentry breadcrumb failed", exc_info=True)

    def set_measurement(self, name: str, value: float, unit: str = "") -> None:
        """Discarded. Metric ingestion is not implemented (ADR-0146).

        ADR-0118 pointed metrics at New Relic; ADR-0146 drops that direction
        without replacing it, so this is honestly unimplemented rather than
        pending a named backend. Kept on the surface because the port declares
        it and a partial adapter that raised here would make every caller
        guard.
        """

    def flush(self, timeout_ms: int = 2000) -> bool:
        try:
            self._sdk.flush(timeout=timeout_ms / 1000)
        except Exception:  # noqa: BLE001 - reporting must not raise
            logger.debug("sentry flush failed", exc_info=True)
            return False
        return True


def build_observability_adapter(credentials: Credentials) -> ObservabilityPort:
    """The adapter this deployment should use: the sensor when a DSN is set.

    Presence of the DSN is the primary switch (ADR-0146): an environment without
    one — tests, CI, the air-gapped sandbox — gets the no-op instead of reaching
    for a network that is not there.

    ``HYDRAFLOW_SENTRY_DISABLED`` overrides it, and the override direction is
    always OFF, so the two settings cannot disagree about anything that matters.
    An earlier draft of this function argued for the DSN alone on exactly that
    "one switch cannot contradict the other" ground. Two facts overrode it.
    First, ``.env`` in a live checkout already carries a ``SENTRY_DSN``, so
    "unset the DSN" is an edit to a credentials file rather than an off-switch
    an operator can reach for. Second, the repo already behaves as though this
    flag works: ``tests/conftest.py`` sets it at import time and three
    regressions (#10876, #11580, #11589) pin it surviving fixture clobbering —
    guards ADR-0118 left behind when it deleted the code that read it. A flag
    that the test suite defends and no production code honours is the same
    dead-consumer shape this ADR exists to fix, pointing the other way.
    """
    import os  # noqa: PLC0415

    from observability.noop_adapter import NoOpObservabilityAdapter  # noqa: PLC0415

    if os.environ.get("HYDRAFLOW_SENTRY_DISABLED", "").strip().lower() not in (
        "",
        "0",
        "false",
        "no",
    ):
        logger.info("observability: disabled by HYDRAFLOW_SENTRY_DISABLED")
        return NoOpObservabilityAdapter()

    dsn = (credentials.sentry_dsn or "").strip()
    if not dsn:
        return NoOpObservabilityAdapter()
    try:
        adapter = SentryObservabilityAdapter(dsn)
    except Exception:  # noqa: BLE001 - a broken reporter must not stop boot
        logger.warning(
            "sentry init failed — falling back to the no-op adapter", exc_info=True
        )
        return NoOpObservabilityAdapter()
    logger.info("observability: exception sensor active (errors only)")
    return adapter
