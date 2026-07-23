"""MockWorld scenario for SkillPromptEvalLoop's prompt-refinement pipeline (#9724).

Drives `_do_work` end-to-end with a REAL `StateTracker`/`DedupStore` on
`tmp_path` and a `FakeGitHub` PR manager (`world.github`) — unlike the unit
coverage in `tests/test_skill_prompt_refine_loop.py`, which exercises
`_try_refine`/`_do_work` against `MagicMock` state and asserts on mock call
history. This tier proves the loop's real persistence layer (attempts,
dedup, weekly-cap window) and a FakeGitHub-backed issue/comment trail agree
with each other across the drift → refine → outcome round-trip.

External I/O the loop would otherwise spawn is stubbed the same way the unit
tests do:

* ``_run_corpus`` — replaced with an ``AsyncMock`` returning a scripted
  case list (never runs `make trust-adversarial`).
* ``generate_and_open_pr_async`` — patched at the LOOP's import site
  (``skill_prompt_eval_loop.generate_and_open_pr_async``, never
  ``auto_pr.generate_and_open_pr_async`` — the loop imported its own
  reference at module load) via ``monkeypatch`` so it is restored even if a
  scenario fails mid-assertion. The fake still invokes the loop's real
  ``generate`` callback against a throwaway git worktree, so the git-apply /
  changed-set-assertion / length-tripwire gates execute for real — only the
  network-facing PR-open call itself is faked.
* ``_validate_candidate`` — stubbed True/False per scenario; the real
  implementation would spawn a live corpus-runner subprocess.

Three scenarios (spec §4.6 self-refinement, #9724):

* ``test_refine_green_path_opens_staging_pr`` — a PASS→FAIL regression with a
  validating candidate patch opens exactly one PR targeting ``staging``, and
  the proposal is persisted without double-counting the repair-attempt
  counter (success is not a repair attempt).
* ``test_refine_red_path_validation_failure_double_increments`` — the same
  regression with a candidate that fails live validation opens no PR,
  double-increments the repair-attempt counter (once for the drift
  regression, once more for the failed refine), and comments the outcome on
  the open drift issue.
* ``test_refine_cap_path_skips_without_llm_call`` — two proposals already
  filed this rolling week hit the weekly cap before the refine LLM is ever
  invoked; the drift issue is still filed (the backstop role is independent
  of the refine kill-switch/cap).
"""

from __future__ import annotations

import asyncio
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

import skill_prompt_eval_loop
from auto_pr import AutoPrResult
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from events import EventBus
from skill_prompt_eval_loop import SkillPromptEvalLoop
from state import StateTracker
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops

_CASE_ID = "case_shrink_001"
_SKILL = "diff-sanity"

# A minimal 2-line builder stub written into the throwaway worktree so the
# loop-side length tripwire (render -> apply -> render) and `git apply`
# exercise real code paths — mirrors `_STUB_BUILDER`/`_GREEN_PATCH` in
# `tests/test_skill_prompt_refine_loop.py`, kept self-contained here since
# scenario tests don't import fixtures from unit-test modules in this repo.
_STUB_BUILDER = (
    "def build_diff_sanity_prompt(*, issue_number, issue_title, diff, **_kwargs):\n"
    '    return "AAAA"\n'
)
_GREEN_PATCH = (
    "```diff\n"
    "--- a/src/diff_sanity.py\n"
    "+++ b/src/diff_sanity.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def build_diff_sanity_prompt(*, issue_number, issue_title, diff, **_kwargs):\n"
    '-    return "AAAA"\n'
    '+    return "BBBB"\n'
    "```"
)


class _FakeRefineLLM:
    """Deterministic, network-free stand-in for the refine LLM client."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self._response


def _drift_case() -> dict[str, Any]:
    return {
        "case_id": _CASE_ID,
        "skill": _SKILL,
        "expected_catcher": _SKILL,
        "status": "FAIL",
    }


def _make_stub_worktree(tmp_path: Path) -> Path:
    """A minimal, committed git repo (not just a bare directory) so the
    changed-set assertion's `git status --porcelain` call has a repo to run
    against — same shape as the unit-test fixture of the same name."""
    wt = tmp_path / "wt"
    (wt / "src").mkdir(parents=True)
    (wt / "src" / "diff_sanity.py").write_text(_STUB_BUILDER, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=wt, check=True)
    subprocess.run(["git", "add", "-A"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "stub"], cwd=wt, check=True)
    return wt


class _RecordingAutoPR:
    """Fake for `generate_and_open_pr_async`, patched at the loop's import
    site (`skill_prompt_eval_loop.generate_and_open_pr_async`).

    Records every call's kwargs so the scenario can assert on `base` /
    `pr_title` / call count, then runs the caller's `generate` callback
    against a real throwaway worktree — exercising the git-apply /
    changed-set-assertion / length-tripwire gates for real — and mirrors
    `generate_and_open_pr_async`'s failed-result-on-exception contract so a
    tripped gate or a failed validation surfaces as `AutoPrResult(status=
    "failed")` exactly like the production helper would.
    """

    def __init__(self, worktree: Path, *, status: str = "opened") -> None:
        self._worktree = worktree
        self._status = status
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        *,
        generate: Any,
        branch: str,
        pr_title: str,
        pr_body: Any,
        base: str,
        **kwargs: Any,
    ) -> AutoPrResult:
        self.calls.append(
            {"branch": branch, "pr_title": pr_title, "base": base, **kwargs}
        )
        try:
            await generate(self._worktree)
        except RuntimeError as exc:
            # Every gate the real `generate` callback raises through (git
            # apply failure, the changed-set assertion, the length
            # tripwire, failed validation) is a `RuntimeError` — narrower
            # than the production helper's blanket `except Exception`, but
            # exhaustive for this fake's only caller.
            return AutoPrResult(
                status="failed", pr_url=None, branch=branch, error=str(exc)
            )
        _ = pr_body() if callable(pr_body) else pr_body
        return AutoPrResult(
            status=self._status, pr_url="https://github.com/x/y/pull/7", branch=branch
        )


def _build_loop(
    world: MockWorld,
    tmp_path: Path,
    *,
    refine_llm: Any,
    preload_proposals: int = 0,
    max_weekly: int = 2,
) -> SkillPromptEvalLoop:
    """A SkillPromptEvalLoop wired to `world.github` (FakeGitHub) with a REAL
    StateTracker/DedupStore on `tmp_path` — never MagicMock state, so
    assertions on persisted attempts/dedup/weekly-cap reflect the real
    persistence layer round-tripping through the loop's own code paths.
    """
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    # Deterministic regardless of this host's HYDRAFLOW_STAGING_ENABLED —
    # the green-path assertion pins PRs to target staging (ADR-0042).
    cfg.staging_enabled = True
    cfg.skill_prompt_refine_max_weekly = max_weekly

    state = StateTracker(state_file=tmp_path / "state.json")
    state.set_skill_prompt_last_green({_CASE_ID: "PASS"})
    now = datetime.now(UTC)
    for _ in range(preload_proposals):
        state.record_refine_proposal(now.isoformat())

    dedup = DedupStore("skill_prompt_eval", tmp_path / "dedup.json")

    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )

    return SkillPromptEvalLoop(
        config=cfg,
        state=state,
        pr_manager=world.github,
        dedup=dedup,
        deps=deps,
        refine_llm=refine_llm,
    )


async def test_refine_green_path_opens_staging_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seeded PASS->FAIL regression + a fake LLM's good builder patch +
    validation stubbed True -> exactly one `generate_and_open_pr_async` call
    targeting staging, whose title names the regressed skill, and the
    proposal is persisted without double-counting the attempt counter."""
    world = MockWorld(tmp_path)
    fake_llm = _FakeRefineLLM(_GREEN_PATCH)
    loop = _build_loop(world, tmp_path, refine_llm=fake_llm)
    loop._run_corpus = AsyncMock(return_value=[_drift_case()])  # type: ignore[method-assign]
    loop._validate_candidate = AsyncMock(return_value=True)  # type: ignore[method-assign]

    fake_pr = _RecordingAutoPR(_make_stub_worktree(tmp_path))
    monkeypatch.setattr(skill_prompt_eval_loop, "generate_and_open_pr_async", fake_pr)

    stats = await loop._do_work()

    assert stats["filed"] == 1
    drift_issues = await world.github.list_issues_by_label("skill-prompt-drift")
    assert len(drift_issues) == 1

    assert len(fake_pr.calls) == 1
    call = fake_pr.calls[0]
    assert call["base"] == "staging"
    assert _SKILL in call["pr_title"]
    assert fake_llm.calls, "refine LLM must actually be invoked on the green path"

    now = datetime.now(UTC)
    assert loop._state.refine_proposals_last_7d(now) == 1
    # Success is not a repair attempt: only `_do_work`'s own drift-regression
    # bump counts, `_try_refine` must not add a second one on "proposed".
    assert loop._state.get_skill_prompt_attempts(_CASE_ID) == 1
    # No non-shipping outcome comment on a successful proposal.
    issue_number = drift_issues[0]["number"]
    assert world.github.issue(issue_number).comments == []


async def test_refine_red_path_validation_failure_double_increments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same regression, but the candidate fails live validation -> no PR
    opens, the repair-attempt counter double-increments (drift regression +
    failed refine), and the outcome is commented on the open drift issue."""
    world = MockWorld(tmp_path)
    fake_llm = _FakeRefineLLM(_GREEN_PATCH)
    loop = _build_loop(world, tmp_path, refine_llm=fake_llm)
    loop._run_corpus = AsyncMock(return_value=[_drift_case()])  # type: ignore[method-assign]
    loop._validate_candidate = AsyncMock(return_value=False)  # type: ignore[method-assign]

    fake_pr = _RecordingAutoPR(_make_stub_worktree(tmp_path))
    monkeypatch.setattr(skill_prompt_eval_loop, "generate_and_open_pr_async", fake_pr)

    stats = await loop._do_work()

    assert stats["filed"] == 1
    drift_issues = await world.github.list_issues_by_label("skill-prompt-drift")
    assert len(drift_issues) == 1

    # The candidate's `generate` callback ran (proving validation was really
    # exercised) but the helper never reports "opened" -> no proposal ships.
    assert len(fake_pr.calls) == 1
    now = datetime.now(UTC)
    assert loop._state.refine_proposals_last_7d(now) == 0

    # One bump from `_do_work`'s drift-regression path, one more from
    # `_try_refine`'s non-shipping "validation_failed" outcome.
    assert loop._state.get_skill_prompt_attempts(_CASE_ID) == 2

    issue_number = drift_issues[0]["number"]
    comments = world.github.issue(issue_number).comments
    assert len(comments) == 1
    assert "did not land" in comments[0]
    assert "validation_failed" in comments[0]


async def test_refine_cap_path_skips_without_llm_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two proposals already filed this rolling week -> refine is skipped
    before the LLM is ever invoked, but the drift issue is still filed (the
    backstop role fires independently of the refine cap)."""
    world = MockWorld(tmp_path)
    fake_llm = _FakeRefineLLM(_GREEN_PATCH)
    loop = _build_loop(
        world, tmp_path, refine_llm=fake_llm, preload_proposals=2, max_weekly=2
    )
    loop._run_corpus = AsyncMock(return_value=[_drift_case()])  # type: ignore[method-assign]

    fake_pr = AsyncMock()
    monkeypatch.setattr(skill_prompt_eval_loop, "generate_and_open_pr_async", fake_pr)

    stats = await loop._do_work()

    assert stats["filed"] == 1
    drift_issues = await world.github.list_issues_by_label("skill-prompt-drift")
    assert len(drift_issues) == 1

    assert fake_llm.calls == []
    fake_pr.assert_not_awaited()

    # "capped" is not a repair attempt (mirrors "proposed"/"disabled") — only
    # the drift-regression bump counts.
    assert loop._state.get_skill_prompt_attempts(_CASE_ID) == 1
    now = datetime.now(UTC)
    assert loop._state.refine_proposals_last_7d(now) == 2
