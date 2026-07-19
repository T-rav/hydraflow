"""Measure the PR-unsticker "reflect on fix" role's pattern-extraction quality.

`PRUnsticker._reflect_on_fix` is a one-shot LLM call (Model-Routing dial:
`pr_unstick_provider` + `background_model`). After a successful CI-timeout fix it
reads the transcript, compares the root cause against already-known
troubleshooting patterns, and either emits a NEW reusable pattern or outputs
`NO_NEW_PATTERN`. Getting this wrong is costly in both directions: a false
"novel" pollutes the store with duplicates; a false "known" drops a real
learning. This eval is the gate before flipping that dial to a cheaper backend.

Each case seeds the store with a fixed set of known patterns and pins the ground
truth: DUP cases (root cause already known) must return ``None``; NOVEL cases
(distinct root cause) must return a pattern whose text recalls the root-cause
keywords. Two checkable proxies, no subjective judge.

    # baseline (config dials, usually claude/haiku):
    uv run pytest tests/evals/test_pr_unstick_evals.py -m evals -v
    # candidate:
    HYDRAFLOW_EVAL_PROVIDER=openrouter HYDRAFLOW_EVAL_MODEL=deepseek/deepseek-chat \\
      uv run pytest tests/evals/test_pr_unstick_evals.py -m evals -v

Real LLM calls — the quality test carries the ``evals`` marker so it is excluded
from the default suite. The ``*_corpus_wellformed`` test makes no model call and
runs in the default suite so a malformed corpus is caught in CI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from troubleshooting_store import (
        TroubleshootingPattern,
    )

CORPUS_ROOT = Path(__file__).parent / "corpus" / "pr_unstick"

# Aggregate bar across the corpus: correct dup-classification + correct
# novel-keyword-recall. Set to catch a backend that either over-emits duplicate
# patterns or drops the root cause, not to demand a perfect run.
_QUALITY_BAR = 0.75

# Fixed issue number for the reflection call — the value is irrelevant to the
# judgment, it only tags the emitted pattern's source_issues.
_ISSUE_NUMBER = 424242


@dataclass(frozen=True)
class Case:
    name: str
    language: str
    transcript: str
    known_patterns: list[dict[str, str]]
    expect_novel: bool
    must_mention: list[str] = field(default_factory=list)
    notes: str = ""


def _load_cases() -> list[Case]:
    cases: list[Case] = []
    for path in sorted(CORPUS_ROOT.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        cases.append(
            Case(
                name=data["name"],
                language=data["language"],
                transcript=data["transcript"],
                known_patterns=list(data["known_patterns"]),
                expect_novel=bool(data["expect_novel"]),
                must_mention=list(data.get("must_mention", [])),
                notes=data.get("notes", ""),
            )
        )
    return cases


class _FakeTroubleshootingStore:
    """Minimal store stand-in — `_reflect_on_fix` only reads `load_patterns`.

    Seeds a fixed set of known patterns so the reflection prompt can compare the
    transcript's root cause against them.
    """

    def __init__(self, patterns: list[TroubleshootingPattern]) -> None:
        self._patterns = patterns

    def load_patterns(
        self, *, language: str | None = None, limit: int | None = 10
    ) -> list[TroubleshootingPattern]:
        return list(self._patterns)


def _seed_patterns(case: Case) -> list[TroubleshootingPattern]:
    from troubleshooting_store import TroubleshootingPattern

    return [
        TroubleshootingPattern(
            language=case.language,
            pattern_name=kp["pattern_name"],
            description=kp["description"],
            fix_strategy=kp.get("fix_strategy", "(known fix strategy)"),
        )
        for kp in case.known_patterns
    ]


def _make_unsticker(config: HydraFlowConfig, store: _FakeTroubleshootingStore):
    """Construct a PRUnsticker wired for `_reflect_on_fix` only.

    Real runner (via `agents._runner`), real config/credentials/event bus, and
    the fake store. Everything `_reflect_on_fix` never touches is a MagicMock.
    """
    from config import Credentials
    from events import EventBus
    from execution import get_default_runner
    from pr_unsticker import PRUnsticker
    from troubleshooting_store import TroubleshootingPatternStore

    agents = MagicMock()
    agents._runner = get_default_runner()

    return PRUnsticker(
        config=config,
        state=MagicMock(),
        event_bus=EventBus(),
        pr_manager=MagicMock(),
        agents=agents,
        workspaces=MagicMock(),
        fetcher=MagicMock(),
        troubleshooting_store=cast(TroubleshootingPatternStore, store),
        credentials=Credentials(),
    )


@pytest.fixture(scope="module")
def eval_config():
    from config import HydraFlowConfig
    from tests.evals._provider_override import apply_provider_override

    config = HydraFlowConfig()
    # pr_unstick has no dedicated *_model dial — the reflection call uses
    # background_model, so that is the override field.
    apply_provider_override(
        config,
        provider_field="pr_unstick_provider",
        model_field="background_model",
    )
    return config


@pytest.mark.evals
@pytest.mark.asyncio
async def test_reflect_on_fix_quality(eval_config) -> None:
    """DUP cases must return None; NOVEL cases must return a pattern that recalls
    the root-cause keywords. Aggregate correctness must clear the bar."""
    from tests.evals._provider_override import backend_label

    cases = _load_cases()
    assert cases, "corpus is empty — add cases under corpus/pr_unstick/"

    scores: list[float] = []
    report = ["", f"=== pr-unstick reflect eval [backend: {backend_label()}] ==="]
    for case in cases:
        store = _FakeTroubleshootingStore(_seed_patterns(case))
        unsticker = _make_unsticker(eval_config, store)
        pattern = await unsticker._reflect_on_fix(
            case.transcript,
            _ISSUE_NUMBER,
            case.language,
        )

        if not case.expect_novel:
            correct = pattern is None
            scores.append(1.0 if correct else 0.0)
            got = "None" if pattern is None else f"pattern:{pattern.pattern_name}"
            mark = "OK" if correct else "XX"
            report.append(f"  [{mark}] {case.name:32} DUP  expected=None got={got}")
            continue

        if pattern is None:
            scores.append(0.0)
            report.append(f"  [XX] {case.name:32} NOVEL expected=pattern got=None")
            continue

        blob = f"{pattern.description} {pattern.fix_strategy}".lower()
        missing = [kw for kw in case.must_mention if kw.lower() not in blob]
        recall = (
            (len(case.must_mention) - len(missing)) / len(case.must_mention)
            if case.must_mention
            else 1.0
        )
        scores.append(recall)
        mark = "OK" if not missing else "XX"
        report.append(
            f"  [{mark}] {case.name:32} NOVEL recall={recall:.2f} "
            f"name={pattern.pattern_name}" + (f" missing={missing}" if missing else "")
        )

    aggregate = sum(scores) / len(scores)
    report.append(f"  --- aggregate score: {aggregate:.2f} (bar {_QUALITY_BAR}) ---")
    print("\n".join(report))

    assert aggregate >= _QUALITY_BAR, (
        f"aggregate pr-unstick reflect score {aggregate:.2f} below {_QUALITY_BAR} "
        "— this backend mis-classifies dup vs novel or drops the root cause. "
        "See the per-case report above."
    )


def test_pr_unstick_corpus_wellformed() -> None:
    """Corpus-shape check (no model call) — runs in the default suite so a
    malformed case is caught in CI, not only when the eval is run."""
    cases = _load_cases()
    assert len(cases) >= 4, "corpus should hold at least 4 cases"

    novel = [c for c in cases if c.expect_novel]
    dup = [c for c in cases if not c.expect_novel]
    assert len(novel) >= 2, "corpus needs at least 2 novel cases"
    assert len(dup) >= 2, "corpus needs at least 2 dup cases"

    for case in cases:
        assert case.transcript.strip(), f"{case.name}: empty transcript"
        assert case.known_patterns, f"{case.name}: no known patterns to seed"
        for kp in case.known_patterns:
            assert kp.get("pattern_name"), f"{case.name}: known pattern missing name"
            assert kp.get("description"), f"{case.name}: known pattern missing desc"
        assert case.notes, f"{case.name}: add notes explaining the ground truth"
        if case.expect_novel:
            assert case.must_mention, (
                f"{case.name}: a novel case must carry root-cause keywords"
            )
