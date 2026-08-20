"""Gateway coverage caretaker state-accessor tests."""

from pathlib import Path

from tests.conftest import make_state


def test_gateway_coverage_attempts_round_trip(tmp_path: Path) -> None:
    state = make_state(tmp_path)

    assert state.get_gateway_coverage_attempts("snapshot") == 0
    assert state.inc_gateway_coverage_attempts("snapshot") == 1
    assert state.get_gateway_coverage_attempts("snapshot") == 1

    state.clear_gateway_coverage_attempts("snapshot")

    assert state.get_gateway_coverage_attempts("snapshot") == 0


def test_gateway_coverage_ceiling_and_regression_state_is_durable(
    tmp_path: Path,
) -> None:
    state = make_state(tmp_path)

    assert state.gateway_coverage_ceiling_achieved() is False
    state.mark_gateway_coverage_ceiling_achieved()
    state.mark_gateway_coverage_ceiling_achieved()
    assert state.gateway_coverage_ceiling_achieved() is True
    assert state.record_gateway_coverage_regression() == 1

    reloaded = make_state(tmp_path)
    assert reloaded.gateway_coverage_ceiling_achieved() is True
    assert reloaded.get_gateway_coverage_attempts("post-ceiling-regression") == 1
