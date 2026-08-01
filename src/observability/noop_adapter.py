"""No-op implementation of ``ObservabilityPort``.

This is the placeholder observability backend until the SRE agent wires a
real adapter (New Relic) per ADR-0118. It is a null object: every method
accepts the port's arguments and does nothing. The ``ObservabilityPort``
seam is preserved so that adapter can slot in without touching call sites.
"""

from __future__ import annotations


class NoOpObservabilityAdapter:
    """ObservabilityPort implementation that discards every event.

    Constructed once at service-registry time and injected wherever the port
    is consumed. Keeps the observability seam alive with zero behavior until a
    real backend (New Relic) is wired by the SRE agent (ADR-0118).
    """

    # Distinguishes the real (production) adapter from a test Fake.
    _is_fake_adapter: bool = False

    def capture_exception(self, exc: BaseException) -> None:
        """Discard *exc* — no observability backend is wired."""

    def capture_message(self, message: str, *, level: str = "info") -> None:
        """Discard *message* — no observability backend is wired."""

    def breadcrumb(self, category: str, message: str, **data: object) -> None:
        """Discard the breadcrumb — no observability backend is wired."""

    def set_measurement(self, name: str, value: float, unit: str = "") -> None:
        """Discard the measurement — no observability backend is wired."""

    def flush(self, timeout_ms: int = 2000) -> bool:
        """Nothing is buffered; report success."""
        return True
