"""Measure ADR review-panel decision accuracy on a curated corpus.

The ADR-review role (``ADRReviewPanel``) role-plays a 3-judge review panel
(architect / pragmatist / editor) in a single completion routed through the
``adr_review_provider``/``adr_review_model``/``adr_review_tool`` dials
(Settings > Model Routing). This eval is the gate before flipping that dial to
a cheaper backend: each case pins the decision a competent panel MUST reach
(ACCEPT a sound significant ADR, REQUEST_CHANGES a thin/incomplete one, flag a
DUPLICATE), and aggregate accuracy across the corpus is a checkable proxy for
quality that needs no subjective judge.

    # baseline (defaults: claude)
    uv run pytest tests/evals/test_adr_review_evals.py -m evals -v

    # candidate
    HYDRAFLOW_EVAL_PROVIDER=openrouter HYDRAFLOW_EVAL_MODEL=deepseek/deepseek-chat \\
      uv run pytest tests/evals/test_adr_review_evals.py -m evals -v

The quality test makes real LLM calls and carries the ``evals`` marker, so it is
excluded from the default suite. ``test_adr_review_corpus_wellformed`` makes no
model call and is intentionally left unmarked so it runs on every ``pytest``
tick and catches a malformed corpus in CI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

CORPUS_ROOT = Path(__file__).parent / "corpus" / "adr_review"

# Aggregate bar: a competent panel agrees with the human label on most cases.
# Set to catch a backend that systematically mislabels, not to demand a perfect
# score on every borderline judgment.
_ACCURACY_BAR = 0.75

# The canonical final_decision values ADRReviewPanelResult.final_decision can hold,
# per src/models.py (uppercase: ACCEPT, REJECT, REQUEST_CHANGES, DUPLICATE,
# NO_CONSENSUS). Note: "ACCEPT" is the approval value — the per-judge VERDICT
# uses "APPROVE", but the panel's final_decision uses "ACCEPT".
_VALID_DECISIONS = frozenset(
    {"ACCEPT", "REJECT", "REQUEST_CHANGES", "DUPLICATE", "NO_CONSENSUS"}
)


@dataclass(frozen=True)
class Case:
    name: str
    adr_number: int
    adr_title: str
    adr_content: str
    index_context: str
    duplicate_context: str
    expected_decision: str
    notes: str


def _load_cases() -> list[Case]:
    cases: list[Case] = []
    for path in sorted(CORPUS_ROOT.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        cases.append(
            Case(
                name=data["name"],
                adr_number=int(data["adr_number"]),
                adr_title=data["adr_title"],
                adr_content=data["adr_content"],
                index_context=data["index_context"],
                duplicate_context=data["duplicate_context"],
                expected_decision=data["expected_decision"],
                notes=data.get("notes", ""),
            )
        )
    return cases


@pytest.fixture(scope="module")
def adr_reviewer():
    """Build a real ADRReviewPanel against the runtime config.

    Uses the production subprocess runner so the model under test matches what
    would ship; ``apply_provider_override`` lets you A/B a candidate backend via
    HYDRAFLOW_EVAL_PROVIDER / _MODEL (a no-op runs on the config default).
    """
    from adr_reviewer import ADRReviewPanel
    from config import HydraFlowConfig
    from events import EventBus
    from execution import get_default_runner
    from tests.evals._provider_override import apply_provider_override

    config = HydraFlowConfig()
    apply_provider_override(
        config,
        provider_field="adr_review_provider",
        model_field="adr_review_model",
    )
    return ADRReviewPanel(config, EventBus(), get_default_runner())


@pytest.mark.evals
@pytest.mark.asyncio
async def test_adr_review_decision_accuracy(adr_reviewer) -> None:
    """Aggregate decision accuracy across the corpus must clear the bar."""
    from tests.evals._provider_override import backend_label

    cases = _load_cases()
    assert cases, "corpus is empty — add cases under corpus/adr_review/"

    correct = 0
    report = ["", f"=== adr-review eval [backend: {backend_label()}] ==="]
    for case in cases:
        result = await adr_reviewer._run_panel_session(
            adr_number=case.adr_number,
            adr_title=case.adr_title,
            adr_content=case.adr_content,
            index_context=case.index_context,
            duplicate_context=case.duplicate_context,
        )
        actual = result.final_decision
        ok = actual == case.expected_decision
        correct += int(ok)
        report.append(
            f"  [{'OK' if ok else 'XX'}] {case.name:40} "
            f"expected={case.expected_decision} actual={actual}"
        )

    accuracy = correct / len(cases)
    report.append(f"  --- accuracy: {accuracy:.2f} (bar {_ACCURACY_BAR}) ---")
    print("\n".join(report))

    assert accuracy >= _ACCURACY_BAR, (
        f"decision accuracy {accuracy:.2f} below {_ACCURACY_BAR} — this backend "
        "mislabels ADRs. See per-case expected/actual above."
    )


def test_adr_review_corpus_wellformed() -> None:
    """Corpus-shape check (no model call) — runs in the default suite so a
    malformed case is caught in CI, not only when the eval is run."""
    cases = _load_cases()
    assert len(cases) >= 4, "corpus should hold at least 4 cases"
    for case in cases:
        assert case.adr_content.strip(), f"{case.name}: empty adr_content"
        assert case.expected_decision in _VALID_DECISIONS, (
            f"{case.name}: invalid expected_decision {case.expected_decision!r} "
            f"(valid: {sorted(_VALID_DECISIONS)})"
        )
        assert case.notes, f"{case.name}: add notes explaining the expected decision"

    decisions = {c.expected_decision for c in cases}
    for required in ("ACCEPT", "REQUEST_CHANGES", "DUPLICATE"):
        assert required in decisions, (
            f"corpus needs at least one {required} case (have: {sorted(decisions)})"
        )
