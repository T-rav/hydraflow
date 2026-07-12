"""Measure transcript-summary quality via key-fact recall on a corpus.

The transcript_summary loop is a one-shot maintenance role (Model-Routing dial),
so it's a candidate to run on a cheap OpenRouter model. This eval is the gate:
each case pins the facts a faithful summary MUST retain; recall of those facts
is a checkable proxy for quality that needs no subjective judge. Run it on the
baseline and a candidate backend and compare before flipping the dial.

    # baseline
    uv run pytest tests/evals/test_transcript_summary_evals.py -m evals -v
    # candidate
    HYDRAFLOW_EVAL_PROVIDER=openrouter HYDRAFLOW_EVAL_MODEL=deepseek/deepseek-chat \\
      uv run pytest tests/evals/test_transcript_summary_evals.py -m evals -v

Real LLM calls — excluded from the default suite by the ``evals`` marker.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

CORPUS_ROOT = Path(__file__).parent / "corpus" / "transcript_summary"
pytestmark = pytest.mark.evals

# Aggregate recall bar: a faithful summary keeps most of the key facts. Set to
# catch a backend that drops material detail, not to demand verbatim coverage.
_RECALL_BAR = 0.80


@dataclass(frozen=True)
class Case:
    name: str
    transcript: str
    must_include: list[str]
    notes: str


def _load_cases() -> list[Case]:
    cases: list[Case] = []
    for path in sorted(CORPUS_ROOT.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        cases.append(
            Case(
                name=data["name"],
                transcript=data["transcript"],
                must_include=list(data["must_include"]),
                notes=data.get("notes", ""),
            )
        )
    return cases


def _recall(summary: str, must_include: list[str]) -> tuple[float, list[str]]:
    """Fraction of required facts present (case-insensitive substring), plus the
    list of facts that were dropped."""
    low = summary.lower()
    missing = [kw for kw in must_include if kw.lower() not in low]
    hit = len(must_include) - len(missing)
    return (hit / len(must_include) if must_include else 1.0), missing


async def _summarize(config, transcript: str) -> str:
    """Run the real transcript-summary prompt through the role's configured
    backend (honouring its provider/model dials). Fails loudly if the model is
    unreachable — evals run only where credentials exist."""
    from execution import get_default_runner
    from runner_utils import run_lightweight_agent
    from transcript_summarizer import _SUMMARIZATION_PROMPT

    result = await run_lightweight_agent(
        runner=get_default_runner(),
        config=config,
        tool=config.transcript_summary_tool,
        model=config.transcript_summary_model,
        provider=config.transcript_summary_provider,
        prompt=_SUMMARIZATION_PROMPT.format(transcript=transcript),
        source="transcript_summary_eval",
        timeout=config.transcript_summary_timeout,
    )
    assert result.returncode == 0, (
        f"summary model unavailable (rc={result.returncode}): {result.stderr[:200]}"
    )
    return result.stdout


@pytest.fixture(scope="module")
def eval_config():
    from config import HydraFlowConfig
    from tests.evals._provider_override import apply_provider_override

    config = HydraFlowConfig()
    apply_provider_override(
        config,
        provider_field="transcript_summary_provider",
        model_field="transcript_summary_model",
    )
    return config


@pytest.mark.asyncio
async def test_summary_key_fact_recall(eval_config) -> None:
    """Aggregate key-fact recall across the corpus must clear the bar."""
    from tests.evals._provider_override import backend_label

    cases = _load_cases()
    assert cases, "corpus is empty — add cases under corpus/transcript_summary/"

    recalls: list[float] = []
    report = ["", f"=== transcript-summary eval [backend: {backend_label()}] ==="]
    for case in cases:
        summary = await _summarize(eval_config, case.transcript)
        recall, missing = _recall(summary, case.must_include)
        recalls.append(recall)
        report.append(
            f"  {case.name:28} recall={recall:.2f}"
            + (f"  missing={missing}" if missing else "")
        )

    mean_recall = sum(recalls) / len(recalls)
    report.append(f"  --- mean recall: {mean_recall:.2f} (bar {_RECALL_BAR}) ---")
    print("\n".join(report))

    assert mean_recall >= _RECALL_BAR, (
        f"mean key-fact recall {mean_recall:.2f} below {_RECALL_BAR} — this "
        "backend drops material detail. See per-case 'missing' above."
    )


def test_transcript_summary_corpus_wellformed() -> None:
    """Corpus-shape check (no model call) — runs in the default suite so a
    malformed case is caught in CI, not only when the eval is run."""
    cases = _load_cases()
    assert len(cases) >= 3, "corpus should hold at least 3 cases"
    for case in cases:
        assert case.transcript.strip(), f"{case.name}: empty transcript"
        assert case.must_include, f"{case.name}: no required facts to check recall"
        assert case.notes, f"{case.name}: add notes explaining the required facts"
