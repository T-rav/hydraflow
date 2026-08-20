"""Regression pin for the live gateway evidence that closes issue #11469."""

from pathlib import Path

from scripts.gateway_probe import ProbeEvidence


def test_issue_11469_live_gateway_session_is_complete_and_byte_exact() -> None:
    """The committed artifact proves agentic transit and exact streamed bytes."""
    fixture = (
        Path(__file__).parents[1]
        / "fixtures"
        / "gateway"
        / "live_provider_probe_evidence.json"
    )
    evidence = ProbeEvidence.model_validate_json(fixture.read_text(encoding="utf-8"))

    assert evidence.live_provider_session is True
    assert evidence.tool_use_observed is True
    assert evidence.completion_observed is True
    assert evidence.key_revocation_verified is True
    assert evidence.raw_capture_cleanup_verified is True

    assert evidence.agent_session is not None
    assert evidence.agent_session.actual_agent_cli is True
    assert evidence.agent_session.tool_call_count > 0
    assert (
        evidence.agent_session.tool_result_count
        == evidence.agent_session.tool_call_count
    )

    for turn in (evidence.first_turn, evidence.second_turn):
        assert turn.status_code == 200
        assert turn.byte_identical is True
        assert turn.downstream == turn.captured_upstream
