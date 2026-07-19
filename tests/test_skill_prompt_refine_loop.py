"""Config knobs + weekly-cap state + refine pipeline for prompt-refinement (#9724)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import skill_prompt_eval_loop
from auto_pr import AutoPrResult
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from skill_prompt_eval_loop import SkillPromptEvalLoop
from state import StateTracker


def test_refine_config_defaults() -> None:
    from config import HydraFlowConfig

    cfg = HydraFlowConfig()
    assert cfg.skill_prompt_refine_enabled is True
    assert cfg.skill_prompt_refine_max_weekly == 2
    assert cfg.skill_prompt_refine_model == ""


def test_weekly_cap_state_prunes(tmp_path) -> None:
    st = StateTracker(state_file=tmp_path / "state.json")
    now = datetime.now(UTC)
    st.record_refine_proposal((now - timedelta(days=8)).isoformat())
    st.record_refine_proposal(now.isoformat())
    assert st.refine_proposals_last_7d(now) == 1


def test_weekly_cap_normalizes_naive_stored_timestamp(tmp_path) -> None:
    """A legacy naive (offset-less) stored timestamp is treated as UTC — it must
    count/prune against a tz-aware ``now`` without raising ``TypeError`` on the
    naive-vs-aware comparison (Task-5 review hardening)."""
    now = datetime.now(UTC)

    recent = StateTracker(state_file=tmp_path / "recent.json")
    recent.record_refine_proposal(now.replace(tzinfo=None).isoformat())
    assert recent.refine_proposals_last_7d(now) == 1

    old = StateTracker(state_file=tmp_path / "old.json")
    old.record_refine_proposal(
        (now - timedelta(days=8)).replace(tzinfo=None).isoformat()
    )
    assert old.refine_proposals_last_7d(now) == 0


# ---------------------------------------------------------------------------
# Refine pipeline (Task 6) — `_try_refine`
# ---------------------------------------------------------------------------


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


def _drift_case() -> dict[str, object]:
    return {
        "case_id": "accidental-deletion",
        "skill": "diff-sanity",
        "expected_catcher": "diff-sanity",
        "status": "FAIL",
    }


class _FakeRefineLLM:
    """Deterministic, network-free stand-in for the refine LLM client."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self._response


GOOD_PATCH = (
    "```diff\n--- a/src/diff_sanity.py\n+++ b/src/diff_sanity.py\n"
    "@@ -1 +1 @@\n-x\n+y\n```"
)

# A minimal 2-line builder stub written into the ephemeral worktree so the
# loop-side length tripwire (render → apply → render) and `git apply` exercise
# real code paths. `_GREEN_PATCH`/`_BALLOON_PATCH` are crafted to apply cleanly
# to exactly this content.
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
_BALLOON_PATCH = (
    "```diff\n"
    "--- a/src/diff_sanity.py\n"
    "+++ b/src/diff_sanity.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def build_diff_sanity_prompt(*, issue_number, issue_title, diff, **_kwargs):\n"
    '-    return "AAAA"\n'
    '+    return "' + "Z" * 400 + '"\n'
    "```"
)


def _make_stub_worktree(tmp_path: Path) -> Path:
    wt = tmp_path / "wt"
    (wt / "src").mkdir(parents=True)
    (wt / "src" / "diff_sanity.py").write_text(_STUB_BUILDER, encoding="utf-8")
    return wt


def _fake_generate_and_open_pr(
    worktree: Path,
    *,
    status: str = "opened",
    pr_url: str | None = "https://github.com/x/y/pull/7",
):
    """Stub for `generate_and_open_pr_async` that runs the caller's generate
    callback against *worktree* (so validation + tripwires execute) and mirrors
    the real helper's failed-result-on-exception contract."""

    async def _fake(*, generate, branch, pr_body, **_kwargs) -> AutoPrResult:
        try:
            await generate(worktree)
        except Exception as exc:  # noqa: BLE001 — mirror helper's failed contract
            return AutoPrResult(
                status="failed", pr_url=None, branch=branch, error=str(exc)
            )
        # Resolve a lazy body to exercise `_refine_pr_body`, as the real helper does.
        _ = pr_body() if callable(pr_body) else pr_body
        return AutoPrResult(status=status, pr_url=pr_url, branch=branch)

    return _fake


@pytest.fixture
def refine_loop_factory(tmp_path: Path):
    def _build(
        *,
        enabled: bool = True,
        llm: object = None,
        preload_proposals: int = 0,
        max_weekly: int = 2,
    ) -> SkillPromptEvalLoop:
        cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
        cfg.skill_prompt_refine_enabled = enabled
        cfg.skill_prompt_refine_max_weekly = max_weekly
        state = StateTracker(state_file=tmp_path / "state.json")
        now = datetime.now(UTC)
        for _ in range(preload_proposals):
            state.record_refine_proposal(now.isoformat())
        pr = AsyncMock()
        pr.find_existing_issue = AsyncMock(return_value=101)
        pr.post_comment = AsyncMock()
        dedup = MagicMock()
        dedup.get.return_value = set()
        return SkillPromptEvalLoop(
            config=cfg,
            state=state,
            pr_manager=pr,
            dedup=dedup,
            deps=_deps(asyncio.Event()),
            refine_llm=llm,
        )

    return _build


async def test_try_refine_respects_kill_switch(refine_loop_factory) -> None:
    loop = refine_loop_factory(enabled=False, llm=_FakeRefineLLM(GOOD_PATCH))
    assert await loop._try_refine(_drift_case()) == "disabled"
    assert loop._state.get_skill_prompt_attempts("accidental-deletion") == 0


async def test_try_refine_respects_weekly_cap(refine_loop_factory) -> None:
    loop = refine_loop_factory(llm=_FakeRefineLLM(GOOD_PATCH), preload_proposals=2)
    assert await loop._try_refine(_drift_case()) == "capped"
    assert loop._state.get_skill_prompt_attempts("accidental-deletion") == 0


async def test_try_refine_tripwire_rejects_and_counts_attempt(
    refine_loop_factory,
) -> None:
    bad = GOOD_PATCH.replace("src/diff_sanity.py", "src/pr_manager.py")
    loop = refine_loop_factory(llm=_FakeRefineLLM(bad))
    assert await loop._try_refine(_drift_case()) == "tripwire"
    assert loop._state.get_skill_prompt_attempts("accidental-deletion") == 1
    loop._pr.post_comment.assert_awaited_once()


async def test_try_refine_unknown_skill_is_error(refine_loop_factory) -> None:
    loop = refine_loop_factory(llm=_FakeRefineLLM(GOOD_PATCH))
    case = _drift_case()
    case["expected_catcher"] = "not-a-real-skill"
    case["skill"] = "not-a-real-skill"
    assert await loop._try_refine(case) == "error"
    assert loop._state.get_skill_prompt_attempts("accidental-deletion") == 1


async def test_try_refine_proposed_records_and_opens_pr(
    refine_loop_factory, tmp_path, monkeypatch
) -> None:
    wt = _make_stub_worktree(tmp_path)
    loop = refine_loop_factory(llm=_FakeRefineLLM(_GREEN_PATCH))
    loop._validate_candidate = AsyncMock(return_value=True)
    monkeypatch.setattr(
        skill_prompt_eval_loop,
        "generate_and_open_pr_async",
        _fake_generate_and_open_pr(wt),
    )
    assert await loop._try_refine(_drift_case()) == "proposed"
    loop._validate_candidate.assert_awaited_once()
    assert loop._state.refine_proposals_last_7d(datetime.now(UTC)) == 1
    # Proposed is a success outcome — no attempt counted, no drift-issue comment.
    assert loop._state.get_skill_prompt_attempts("accidental-deletion") == 0
    loop._pr.post_comment.assert_not_awaited()


async def test_try_refine_validation_failure_aborts_before_pr(
    refine_loop_factory, tmp_path, monkeypatch
) -> None:
    wt = _make_stub_worktree(tmp_path)
    loop = refine_loop_factory(llm=_FakeRefineLLM(_GREEN_PATCH))
    loop._validate_candidate = AsyncMock(return_value=False)
    monkeypatch.setattr(
        skill_prompt_eval_loop,
        "generate_and_open_pr_async",
        _fake_generate_and_open_pr(wt),
    )
    assert await loop._try_refine(_drift_case()) == "validation_failed"
    assert loop._state.get_skill_prompt_attempts("accidental-deletion") == 1
    assert loop._state.refine_proposals_last_7d(datetime.now(UTC)) == 0


async def test_try_refine_length_tripwire_before_validation(
    refine_loop_factory, tmp_path, monkeypatch
) -> None:
    wt = _make_stub_worktree(tmp_path)
    loop = refine_loop_factory(llm=_FakeRefineLLM(_BALLOON_PATCH))
    loop._validate_candidate = AsyncMock(return_value=True)  # must not be reached
    monkeypatch.setattr(
        skill_prompt_eval_loop,
        "generate_and_open_pr_async",
        _fake_generate_and_open_pr(wt),
    )
    assert await loop._try_refine(_drift_case()) == "tripwire"
    loop._validate_candidate.assert_not_awaited()
    assert loop._state.get_skill_prompt_attempts("accidental-deletion") == 1
    assert loop._state.refine_proposals_last_7d(datetime.now(UTC)) == 0
