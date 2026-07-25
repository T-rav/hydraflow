"""Regression (#10487): RC promotion to main failing CI.

``HydraFlowOrchestrator.__init__`` registers its config in
``trace_collector``'s process-wide active-config slot via
``set_active_config`` but nothing ever resets it back to ``None``. Under
``pytest -n auto --dist loadscope``, any test that builds an orchestrator
(directly, or via MockWorld, which applies the sandbox overrides — including
``auto_pr_preflight_gate_enabled=False`` — before constructing it) left that
config active for whichever test ran next on the same xdist worker.
``auto_pr``'s pre-flight gate (``_preflight_settings``) reads the slot as
ground truth, so the leak silently disabled the gate in
``tests/test_auto_pr_preflight.py`` whenever the scheduler happened to place
a config-leaking test earlier in the same worker's queue — a flake that only
reproduced under the full ``make quality`` run, never in isolation.

``tests/conftest.py``'s ``_reset_active_config`` autouse fixture resets the
slot around every test. This guards it the same way
``test_mock_path_pollution_guard.py`` guards the ``MagicMock``-directory
fixture: reproduce the hook shape inline via ``pytester`` (avoids fragile
path coupling to the repo root's real conftest).
"""

from __future__ import annotations

import pytest

pytest_plugins = ["pytester"]

_LEAKER_AND_VICTIM = {
    "test_leaker": """
        def test_leaks_active_config():
            import trace_collector

            class _FakeConfig:
                auto_pr_preflight_gate_enabled = False

            trace_collector.set_active_config(_FakeConfig())
        """,
    "test_victim": """
        def test_sees_no_leaked_config():
            import trace_collector

            assert trace_collector.get_active_config() is None
        """,
}


def test_active_config_leak_is_reset_between_tests(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(
        """
        import pytest

        import trace_collector


        @pytest.fixture(autouse=True)
        def _reset_active_config():
            trace_collector.set_active_config(None)
            yield
            trace_collector.set_active_config(None)
        """
    )
    pytester.makepyfile(**_LEAKER_AND_VICTIM)
    result = pytester.runpytest("-p", "no:randomly", "-q")
    result.assert_outcomes(passed=2)


def test_without_the_fixture_the_leak_reproduces(pytester: pytest.Pytester) -> None:
    """Sanity check: the scenario above is a real hazard absent the fixture."""
    pytester.makepyfile(**_LEAKER_AND_VICTIM)
    result = pytester.runpytest("-p", "no:randomly", "-q")
    result.assert_outcomes(passed=1, failed=1)
