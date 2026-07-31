"""Regression for #10862: OTel tracer-provider leak must be cleared in SETUP.

A provider installed outside a function's setup/teardown boundary — at module
import, or by a session-/module-scoped fixture in another test subtree such as
``tests/regressions`` — leaks past the autouse ``_reset_otel_tracer_provider``
fixture when that fixture resets only in teardown. OpenTelemetry guards
``set_tracer_provider`` with a ``Once``, so the next ``FakeHoneycomb`` silently
fails to install its ``InMemorySpanExporter`` and captures zero spans instead of
raising (``test_loop_emits_loop_span`` failed under sequential full-tree runs).
The fix makes the reset symmetric — setup as well as teardown.

This module simulates such a leak with a module-scoped autouse fixture and
asserts the function-scoped reset has already cleared it by the time the test
body runs. Under a teardown-only reset the provider is still installed here and
this test fails.
"""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider


@pytest.fixture(scope="module", autouse=True)
def _leak_a_provider():
    """Install a provider once, outside any function setup/teardown boundary.

    Module scope runs before the function-scoped ``_reset_otel_tracer_provider``
    at the first test's setup, mimicking a provider that a module-import or a
    higher-scoped fixture installed and that a teardown-only reset never sees.
    """
    trace._TRACER_PROVIDER_SET_ONCE._done = False  # noqa: SLF001
    trace.set_tracer_provider(TracerProvider())
    yield


def test_leaked_provider_is_cleared_before_next_test() -> None:
    # The module-scoped fixture installed a provider outside this function's
    # setup boundary. A symmetric reset clears it in setup; a teardown-only
    # reset leaves it installed here and silently swallows spans (#10862).
    assert trace._TRACER_PROVIDER is None  # noqa: SLF001
    assert trace._TRACER_PROVIDER_SET_ONCE._done is False  # noqa: SLF001
