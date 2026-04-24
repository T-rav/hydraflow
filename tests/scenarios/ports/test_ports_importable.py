"""Phase 1 smoke test: Port protocols import and are runtime_checkable."""

from __future__ import annotations

import pytest

from tests.scenarios.ports import (
    ClockPort,
    LLMPort,
    SentryPort,
)


@pytest.mark.parametrize("port", [ClockPort, LLMPort, SentryPort])
def test_port_is_runtime_checkable(port: type) -> None:
    # runtime_checkable decorator sets this dunder
    assert getattr(port, "_is_runtime_protocol", False), (
        f"{port.__name__} must be @runtime_checkable"
    )
