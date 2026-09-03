"""Sentry-SDK implementation of ``ObservabilityPort`` — errors only.

The SDK is Sentry's; the TARGET is whatever the DSN names. Bugsink speaks the
same ingest protocol and is the house default (ADR-0146), so this one adapter
serves both — pointing a repo at sentry.io instead is a DSN change, not a code
change. Named after the library it uses rather than the backend it happens to
reach, because the backend is configuration.

This is the outbound half of the exception sensor
(``docs/standards/exception_sensor/``). The inbound half — errors becoming
GitHub issues the pipeline can triage — is ``dashboard_routes/_issue_intake_routes``,
which receives Bugsink's custom webhook. Bugsink has no tracker integration of
its own; an earlier draft of ADR-0146 said it did, and was wrong.

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
import os
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, TypeVar

import sentry_sdk

from observability.noop_adapter import NoOpObservabilityAdapter

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


_T = TypeVar("_T")


def _never_raises(what: str, call: Callable[[], _T], fallback: _T) -> _T:
    """Run *call*, swallowing anything it throws.

    THE one broad catch in this module, deliberately. Observability must never
    fail the work it observes — a loop that dies because its error reporter was
    unreachable has turned a diagnostic into an outage — so the catch has to be
    blind: narrowing it to today's SDK exception types means tomorrow's escapes
    into the caller. Funnelling every method through here keeps that reasoning
    in one place instead of restating it at five call sites, where the fifth
    copy is the one that eventually gets narrowed by a well-meaning cleanup.
    """
    try:
        return call()
    except Exception:  # noqa: BLE001 - see the docstring; this is the point
        logger.debug("sentry %s failed", what, exc_info=True)
        return fallback


#: The component name used when a caller does not say which process it is.
_DEFAULT_COMPONENT = "factory"

#: Records the component this process initialised the SDK for, so a second
#: caller reuses the client instead of re-initialising it. `sentry_sdk.init`
#: replaces the global client wholesale, so the composition root building an
#: adapter after an entrypoint already installed the sensor would silently
#: drop the entrypoint's component tag. A dict rather than a module flag so
#: mutation replaces no binding (and the linter's `global` rule stays happy).
_SDK_STATE: dict[str, str] = {}


def sdk_component() -> str | None:
    """The component this process initialised the SDK for, if it has."""
    return _SDK_STATE.get("component")


def reset_sentry_sdk_state_for_tests() -> None:
    """Forget that the SDK was initialised. Tests only."""
    _SDK_STATE.clear()


def _bugs_only(event: Any, hint: Any) -> Any:
    """Drop error-level log lines that carry no exception.

    Sentry's logging integration promotes EVERY `logger.error` call to an
    event, including the many that report an operational failure in prose and
    attach no exception at all. Those arrive with no stack trace and no
    exception type, which leaves Bugsink grouping them on message text and
    leaves triage a sentence with nothing to act on — a notification, not a
    bug report, and rule 9 would auto-close it as a transient after it had
    already taken a slot on the board.

    An explicit `capture_message` is kept even without an exception: a call
    site that deliberately reaches for the sensor has said what it means. Only
    the *incidental* promotion of a log line is filtered, which is why the
    check is for `log_record` rather than for the absence of an exception.
    """
    if "exc_info" in hint or event.get("exception"):
        return event
    if "log_record" in hint:
        return None
    return event


def init_sentry_sdk(dsn: str, *, component: str) -> bool:
    """Configure the SDK for this process. Idempotent; returns True if it ran.

    The single place `sentry_sdk.init` is called. Both the injected
    `ObservabilityPort` adapter and the entrypoint-level sensor come through
    here, so their options cannot drift apart — and because init replaces the
    global client, the second caller must not run at all.
    """
    if _SDK_STATE.get("component"):
        return False
    try:
        _configure(dsn, component)
    except Exception:  # noqa: BLE001 - a broken reporter must not stop boot
        logger.warning(
            "sentry init failed — falling back to the no-op adapter", exc_info=True
        )
        return False
    _SDK_STATE["component"] = component
    return True


def _configure(dsn: str, component: str) -> None:
    """The raw SDK call, split out so the swallow above has one subject."""
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
        before_send=_bugs_only,
    )
    # Global scope, not the current one: the tag must survive every scope push
    # the loops and the ASGI middleware make, or events lose their origin.
    sentry_sdk.get_global_scope().set_tag("hydraflow.component", component)


def install_process_sensor(
    component: str, *, env: Mapping[str, str] | None = None
) -> bool:
    """Start the sensor for a whole process, from the environment.

    For entrypoints that have no `Credentials` to be handed — the gateway is
    its own deployable — and for the window before one exists. `server.main`
    installs it immediately after logging is configured, which is what puts a
    crash during config load or factory boot on the board: the composition
    root builds the adapter much later, and a process that dies before
    reaching it used to report nothing at all.

    Returns True when the sensor was installed.
    """
    environment = os.environ if env is None else env
    if environment.get("HYDRAFLOW_SENTRY_DISABLED", "").strip().lower() not in (
        "",
        "0",
        "false",
        "no",
    ):
        logger.info("observability: disabled by HYDRAFLOW_SENTRY_DISABLED")
        return False
    dsn = (environment.get("SENTRY_DSN") or "").strip()
    if not dsn:
        return False
    started = init_sentry_sdk(dsn, component=component)
    if started:
        logger.info("observability: exception sensor active for %s", component)
    return started


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

    def __init__(self, dsn: str, *, component: str = _DEFAULT_COMPONENT) -> None:
        self._sdk = sentry_sdk
        init_sentry_sdk(dsn, component=component)

    def capture_exception(self, exc: BaseException) -> None:
        _never_raises(
            "capture_exception", lambda: self._sdk.capture_exception(exc), None
        )

    def capture_message(self, message: str, *, level: str = "info") -> None:
        _never_raises(
            "capture_message",
            lambda: self._sdk.capture_message(message, level=_sentry_level(level)),
            None,
        )

    def breadcrumb(self, category: str, message: str, **data: object) -> None:
        _never_raises(
            "breadcrumb",
            lambda: self._sdk.add_breadcrumb(
                category=category, message=message, data=dict(data)
            ),
            None,
        )

    def set_measurement(self, name: str, value: float, unit: str = "") -> None:
        """Discarded. Metric ingestion is not implemented (ADR-0146).

        ADR-0118 pointed metrics at New Relic; ADR-0146 drops that direction
        without replacing it, so this is honestly unimplemented rather than
        pending a named backend. Kept on the surface because the port declares
        it and a partial adapter that raised here would make every caller
        guard.
        """

    def flush(self, timeout_ms: int = 2000) -> bool:
        def _flush() -> bool:
            self._sdk.flush(timeout=timeout_ms / 1000)
            return True

        return _never_raises("flush", _flush, False)


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
    if (
        not init_sentry_sdk(dsn, component=_DEFAULT_COMPONENT)
        and sdk_component() is None
    ):
        # init_sentry_sdk swallowed a broken reporter and said so; a False with
        # a component already recorded just means this process is bound.
        return NoOpObservabilityAdapter()
    logger.info("observability: exception sensor active (errors only)")
    return SentryObservabilityAdapter(dsn)
