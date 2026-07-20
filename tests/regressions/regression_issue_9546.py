"""Regression pins for issue #9546 — independent test-adequacy verifier.

The verifier is a second-opinion LLM pass that re-derives the adequacy verdict
after the finder emits an explicit ``TEST_ADEQUACY_RESULT: OK``. Two invariants
are load-bearing enough to pin here, because a plausible-looking "cleanup"
would regress either one silently:

1. **Explicit-OK gate.** The trigger predicate must fire ONLY on the explicit
   ``OK`` marker — never on the no-marker default-pass. Every empty-transcript
   FakeLLM scenario (``tests/scenarios/test_agent_realistic.py`` scripts bare
   ``result`` events) relies on the default-pass NOT growing an extra verifier
   subprocess slot. Relaxing the trigger to "any finder pass" would break every
   scripted-FIFO scenario and add silent LLM spend on degraded transcripts.

2. **Model independence.** The verifier's model is configured separately from
   ``review_model`` (the finder's model). Pointing the VerifierSpec back at
   ``review_model`` — an easy "simplification" — would have the same model
   grade its own homework and hollow out the second opinion.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from config import HydraFlowConfig
from skill_registry import BUILTIN_SKILLS
from test_adequacy import finder_asserted_adequate, parse_test_adequacy_result


def _ta_verifier():
    skill = next(s for s in BUILTIN_SKILLS if s.name == "test-adequacy")
    assert skill.verifier is not None, "test-adequacy lost its VerifierSpec"
    return skill.verifier


class TestExplicitOkGatePin:
    """Pin 1: no-marker default-pass must never trigger the verifier."""

    def test_no_marker_transcript_passes_finder_but_not_trigger(self) -> None:
        # This exact asymmetry is the contract: parser default-passes,
        # trigger stays cold.
        for transcript in ("", "   ", "agent chatter without any marker"):
            passed, _, _ = parse_test_adequacy_result(transcript)
            assert passed is True, "finder default-pass regressed"
            assert finder_asserted_adequate(transcript) is False, (
                f"verifier trigger fired on a no-marker transcript {transcript!r}; "
                "empty-transcript FakeLLM scenarios rely on default-pass staying "
                "verifier-free"
            )

    def test_explicit_ok_still_triggers(self) -> None:
        assert finder_asserted_adequate("TEST_ADEQUACY_RESULT: OK\nSUMMARY: fine")

    def test_registered_trigger_is_the_explicit_ok_predicate(self) -> None:
        assert _ta_verifier().trigger is finder_asserted_adequate


class TestModelIndependencePin:
    """Pin 2: verifier model must stay independent of the finder's model."""

    def test_spec_points_at_its_own_model_field(self) -> None:
        spec = _ta_verifier()
        assert spec.model_config_key == "test_adequacy_verifier_model"

    def test_default_models_differ(self) -> None:
        cfg = HydraFlowConfig()
        assert cfg.test_adequacy_verifier_model != cfg.review_model, (
            "verifier and finder share a default model — the second opinion "
            "is the same model grading its own homework"
        )

    def test_fail_soft_is_the_default_policy(self) -> None:
        # Fail-closed is the opt-in knob; flipping the default would turn every
        # degraded verifier run (infra blip, empty transcript) into a retry.
        assert HydraFlowConfig().test_adequacy_verifier_fail_closed is False
