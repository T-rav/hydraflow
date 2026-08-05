"""Unit tests for prompt outcome pairing (#10855) — the rule + gaming detector."""

from __future__ import annotations

from prompt_outcome_pairing import (
    GamingSignal,
    OutcomeSnapshot,
    PairingVerdict,
    detect_markup_only_gain,
    instruction_content,
    minimum_detectable_effect,
    pairing_verdict,
    quality_regressed,
)


def _outcome(
    *,
    pass_rate: float = 0.8,
    retry_rate: float = 1.0,
    escape_rate: float = 0.0,
    cost: float = 1.0,
    n: int = 20,
    model: str = "opus-1",
) -> OutcomeSnapshot:
    return OutcomeSnapshot(
        pass_rate=pass_rate,
        retry_rate=retry_rate,
        escape_rate=escape_rate,
        cost_per_success=cost,
        n_samples=n,
        model_version=model,
    )


# --- the rule --------------------------------------------------------------


def test_score_gain_with_no_regression_is_admissible() -> None:
    verdict = pairing_verdict(
        score_before=0.6,
        score_after=0.9,
        outcome_before=_outcome(pass_rate=0.8),
        outcome_after=_outcome(pass_rate=0.85),  # outcome also improved
    )
    assert verdict is PairingVerdict.ADMISSIBLE


def test_score_gain_with_pass_rate_regression_is_inadmissible() -> None:
    # The Goodhart signature: score up, quality down.
    verdict = pairing_verdict(
        score_before=0.6,
        score_after=0.9,
        outcome_before=_outcome(pass_rate=0.85),
        outcome_after=_outcome(pass_rate=0.70),
    )
    assert verdict is PairingVerdict.SCORE_UP_OUTCOME_DOWN


def test_score_gain_with_more_retries_or_escapes_is_inadmissible() -> None:
    more_retries = pairing_verdict(
        score_before=0.6,
        score_after=0.9,
        outcome_before=_outcome(retry_rate=1.0),
        outcome_after=_outcome(retry_rate=1.5),
    )
    more_escapes = pairing_verdict(
        score_before=0.6,
        score_after=0.9,
        outcome_before=_outcome(escape_rate=0.0),
        outcome_after=_outcome(escape_rate=0.1),
    )
    assert more_retries is PairingVerdict.SCORE_UP_OUTCOME_DOWN
    assert more_escapes is PairingVerdict.SCORE_UP_OUTCOME_DOWN


def test_a_falling_score_is_never_the_rules_business() -> None:
    # The rule only fires on a score *gain* paired with a regression.
    verdict = pairing_verdict(
        score_before=0.9,
        score_after=0.6,
        outcome_before=_outcome(pass_rate=0.85),
        outcome_after=_outcome(pass_rate=0.70),
    )
    assert verdict is PairingVerdict.ADMISSIBLE


def test_insufficient_samples_report_no_verdict() -> None:
    verdict = pairing_verdict(
        score_before=0.6,
        score_after=0.9,
        outcome_before=_outcome(n=2),
        outcome_after=_outcome(n=20, pass_rate=0.5),
    )
    assert verdict is PairingVerdict.INSUFFICIENT_DATA


def test_cross_model_version_comparison_resets() -> None:
    verdict = pairing_verdict(
        score_before=0.6,
        score_after=0.9,
        outcome_before=_outcome(model="opus-1", pass_rate=0.85),
        outcome_after=_outcome(model="opus-2", pass_rate=0.70),
    )
    assert verdict is PairingVerdict.MODEL_VERSION_BOUNDARY


def test_cost_regression_alone_does_not_make_a_score_gain_inadmissible() -> None:
    # Cost is efficiency, not quality — reported, but not a rule trigger.
    assert not quality_regressed(
        _outcome(cost=1.0),
        _outcome(cost=5.0),  # 5x cost, but every quality dim held
    )


def test_sub_materiality_wobble_is_not_a_regression() -> None:
    assert not quality_regressed(
        _outcome(pass_rate=0.80),
        _outcome(pass_rate=0.795),  # 0.005 < 0.02 materiality
    )


def test_minimum_detectable_effect_shrinks_with_samples() -> None:
    assert minimum_detectable_effect(0) == 1.0
    assert minimum_detectable_effect(100) < minimum_detectable_effect(4)
    assert 0.0 < minimum_detectable_effect(25) <= 1.0


# --- gaming-failure-mode detection -----------------------------------------


def test_instruction_content_strips_markup_and_normalizes() -> None:
    plain = "Summarize the issue and list the edge cases."
    tagged = "<task>\n  **Summarize** the `issue` and list the edge cases.\n</task>"
    assert instruction_content(plain) == instruction_content(tagged)


def test_markup_only_score_gain_is_flagged() -> None:
    before = "Summarize the issue and name the constraints."
    after = "<request>\nSummarize the issue and name the constraints.\n</request>"
    signal = detect_markup_only_gain(
        before_text=before,
        after_text=after,
        score_before=0.5,
        score_after=0.9,  # score jumped purely from added structure
    )
    assert signal.is_markup_only_gain is True


def test_real_instruction_change_is_not_flagged() -> None:
    before = "Summarize the issue."
    after = "<request>Summarize the issue AND propose a fix plan.</request>"
    signal = detect_markup_only_gain(
        before_text=before,
        after_text=after,
        score_before=0.5,
        score_after=0.9,
    )
    assert signal.instruction_changed is True
    assert signal.is_markup_only_gain is False


def test_markup_change_without_a_score_gain_is_not_flagged() -> None:
    before = "Summarize the issue."
    after = "<request>Summarize the issue.</request>"
    signal = detect_markup_only_gain(
        before_text=before,
        after_text=after,
        score_before=0.9,
        score_after=0.9,  # no score gain
    )
    assert isinstance(signal, GamingSignal)
    assert signal.is_markup_only_gain is False
