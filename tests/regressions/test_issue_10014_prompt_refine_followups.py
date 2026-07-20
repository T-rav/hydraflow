"""Regression pins for the #9724 prompt-refine follow-ups (#10014).

1. Weekly-backstop live mode was one-transcript: `evaluate_case` built only
   ``BUILTIN_SKILLS[0]``'s (diff-sanity) prompt for the live path, so a live
   run never exercised the other five skills' prompts. The fix routes
   catcher-skill cases through the per-skill live path
   (`evaluate_case_for_skill`, fixtures bypassed) under a case-count budget.

2. ``skill_prompt_refine_model`` is a live settings knob, but the production
   refine client captured the model at first use — a System-tab change was
   silently pinned until restart (the load-time-leak class). The fix resolves
   the model from config on every synthesis call.

3. ``prompt-inefficiency`` dedup keys never cleared on issue close — one
   issue per source, forever. The fix wires the loop's close-reconcile so a
   re-degradation re-files.

4. Widening ``REFINABLE_SKILLS`` also made the ±30% length gate real for the
   document-judging builders: the generic diff-only probe rendered "" for
   them (and for ``plan-compliance``), so before/after lengths were both zero
   and the gate measured nothing.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import skill_prompt_eval_loop
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from prompt_efficiency import SkillEfficiencyRow
from prompt_refiner import (
    REFINABLE_SKILLS,
    SKILL_BUILDER_MODULES,
    render_builder_prompt,
)
from skill_prompt_eval_loop import SkillPromptEvalLoop
from tests.trust.adversarial import corpus_runner

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Item 1 — REFINABLE_SKILLS widened, and the honeypot precondition holds.
# ---------------------------------------------------------------------------


def test_refinable_skills_include_the_formerly_uncovered_three() -> None:
    assert {
        "plan-compliance",
        "discover-completeness",
        "shape-coherence",
    } <= REFINABLE_SKILLS
    assert REFINABLE_SKILLS <= set(SKILL_BUILDER_MODULES)


@pytest.mark.parametrize("skill_name", sorted(SKILL_BUILDER_MODULES))
def test_length_probe_renders_nonempty_for_every_builder(skill_name: str) -> None:
    """The ±30% drift gate is only real when the probe render is non-empty:
    a builder that returns "" for the probe makes before/after both zero and
    the gate a silent no-op. Document-judging builders (and plan-compliance)
    need their probe inputs threaded."""
    rendered = render_builder_prompt(
        _REPO_ROOT / SKILL_BUILDER_MODULES[skill_name], skill_name
    )
    assert rendered.strip(), f"{skill_name}: length-probe render is empty"


# ---------------------------------------------------------------------------
# Item 2 — the live backstop exercises each skill's OWN prompt.
# ---------------------------------------------------------------------------


def test_live_backstop_builds_target_skills_prompt_not_first_skills(
    monkeypatch,
) -> None:
    """Pre-#10014, the live transcript for every fixtureless case came from
    ``BUILTIN_SKILLS[0]``'s prompt. Under the per-skill path the CLI must
    receive the catcher's own prompt — for a discover case that prompt embeds
    the case's issue/brief documents, which only exist via the threaded
    input fixtures."""
    prompts: list[str] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        prompts.append(cmd[2])
        return SimpleNamespace(stdout="unstructured reply\n")

    monkeypatch.setattr(corpus_runner.subprocess, "run", fake_run)

    case_name = "holdout-discover-completeness-attack-shallow-known-unknowns"
    case = corpus_runner.CASES_DIR / case_name
    corpus_runner.run_corpus(
        live=True, case_ids=frozenset({case_name}), live_budget=1
    )

    assert len(prompts) == 1
    first_skill_prompt = corpus_runner.BUILTIN_SKILLS[0].prompt_builder(
        issue_number=0,
        issue_title=f"adversarial-corpus::{case_name}",
        diff=corpus_runner.synthesize_diff(case / "before", case / "after"),
        plan_text=corpus_runner.load_plan_text(case),
    )
    assert prompts[0] != first_skill_prompt
    issue_body = (case / "before" / "issue.md").read_text(encoding="utf-8")
    brief = (case / "after" / "brief.md").read_text(encoding="utf-8")
    assert issue_body.strip() in prompts[0]
    assert brief.strip() in prompts[0]


# ---------------------------------------------------------------------------
# Items 3 + 4 — loop-side seams.
# ---------------------------------------------------------------------------


def _deps() -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


class _FakeDedup:
    def __init__(self, keys: set[str]) -> None:
        self._keys = set(keys)

    def get(self) -> set[str]:
        return set(self._keys)

    def set_all(self, keys: set[str]) -> None:
        self._keys = set(keys)


def _build_loop(
    tmp_path: Path, *, dedup: object | None = None
) -> SkillPromptEvalLoop:
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=7)
    pr.list_issues_by_label = AsyncMock(return_value=[])
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    if dedup is None:
        dedup = MagicMock()
        dedup.get.return_value = set()
    return SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps()
    )


async def test_refine_model_change_takes_effect_without_restart(
    tmp_path: Path, monkeypatch
) -> None:
    """`skill_prompt_refine_model` is live=True in the settings registry; the
    cached production client must re-resolve it per synthesis call instead of
    freezing the value captured at first use."""
    models: list[str] = []

    async def fake_agent(**kwargs: object) -> SimpleNamespace:
        models.append(str(kwargs["model"]))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(skill_prompt_eval_loop, "run_lightweight_agent", fake_agent)
    monkeypatch.setattr(skill_prompt_eval_loop, "get_default_runner", lambda: None)

    loop = _build_loop(tmp_path)
    loop._config.skill_prompt_refine_model = "model-first"
    await loop._refine_llm_complete("synthesize")
    loop._config.skill_prompt_refine_model = "model-second"
    await loop._refine_llm_complete("synthesize again")

    assert models == ["model-first", "model-second"]


async def test_closing_inefficiency_issue_clears_dedup_and_refiling_works(
    tmp_path: Path,
) -> None:
    """Closing a `prompt-inefficiency` issue must clear its dedup key via the
    loop's close-reconcile so a re-degradation of the same source re-files —
    previously the key lived forever (one issue per source, ever)."""
    source = "diff-sanity"
    key = f"skill_prompt_eval:inefficiency:{source}"
    dedup = _FakeDedup({key})
    loop = _build_loop(tmp_path, dedup=dedup)

    def closed_by_label(label: str, limit: int = 100) -> list[dict[str, object]]:
        del limit
        if label == skill_prompt_eval_loop._INEFFICIENCY_LABEL:
            return [
                {
                    "number": 555,
                    "title": skill_prompt_eval_loop._inefficiency_title(source),
                    "body": "",
                    "updated_at": "",
                }
            ]
        return []

    loop._pr.list_closed_issues_by_label = AsyncMock(side_effect=closed_by_label)

    await loop._reconcile_closed_escalations()

    assert key not in dedup.get()
    # A source-name subject must never leak into the drift-case attempt
    # counters — that clear belongs to the skill-prompt-stuck reconciler.
    loop._state.clear_skill_prompt_attempts.assert_not_called()

    # Re-degradation now re-files instead of being dedup-swallowed.
    row = SkillEfficiencyRow(
        source=source,
        calls=100,
        est_cost_usd=10.0,
        anomalies=0,
        cost_per_call=0.1,
        trend_vs_baseline=0.9,
    )
    await loop._file_inefficiency_issue(row)
    loop._pr.create_issue.assert_awaited_once()
    labels = loop._pr.create_issue.await_args.args[2]
    assert skill_prompt_eval_loop._INEFFICIENCY_LABEL in labels
    assert key in dedup.get()


async def test_run_corpus_forwards_live_budget_env(tmp_path: Path, monkeypatch) -> None:
    """The weekly backstop forwards the operator's live-case budget knob to
    the harness (mirroring MAX_CASES) so the per-skill live path is bounded."""
    captured: dict[str, dict[str, str]] = {}

    async def fake_exec(*_cmd: str, **kwargs: object) -> object:
        captured["env"] = kwargs["env"]

        class _Proc:
            returncode = 0

            async def communicate(self) -> tuple[bytes, bytes]:
                return (b"[]", b"")

        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    loop = _build_loop(tmp_path)
    result = await loop._run_corpus()

    assert result == []
    budget = captured["env"]["HYDRAFLOW_TRUST_ADVERSARIAL_LIVE_BUDGET"]
    assert budget == str(loop._config.skill_prompt_eval_live_case_budget)
    assert loop._config.skill_prompt_eval_live_case_budget == (
        corpus_runner.DEFAULT_LIVE_BUDGET
    )
