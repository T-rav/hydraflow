"""Config knobs + weekly-cap state + refine pipeline for prompt-refinement (#9724)."""

from __future__ import annotations

import asyncio
import subprocess
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
    """A minimal, committed git repo (not just a bare directory) so the
    changed-set assertion's `git status --porcelain` call has a repo to run
    against."""
    wt = tmp_path / "wt"
    (wt / "src").mkdir(parents=True)
    (wt / "src" / "diff_sanity.py").write_text(_STUB_BUILDER, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=wt, check=True)
    subprocess.run(["git", "add", "-A"], cwd=wt, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "stub"], cwd=wt, check=True)
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


# ---------------------------------------------------------------------------
# `_assert_only_module_changed` — closes the git-apply `-p1` prefix-
# differential bypass (code review Finding 1): `git apply` defaults to `-p1`
# (strips ANY single leading path component) but `check_tripwires` only
# recognizes literal `a/`/`b/` prefixes, so a patch section headed
# `--- x/<path>` / `+++ y/<path>` applies cleanly and is invisible to the
# tripwire scan. The changed-set assertion is git-native ground truth: it
# compares what `git status --porcelain` says actually changed against the
# single expected target, independent of the patch's own prefix scheme.
# ---------------------------------------------------------------------------


def _init_git_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """A committed git repo under *tmp_path*, seeded with *files* (relative
    path -> content)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", rel], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
    return repo


async def test_assert_only_module_changed_passes_when_only_module_touched(
    tmp_path: Path,
) -> None:
    repo = _init_git_repo(tmp_path, {"src/diff_sanity.py": "a = 1\n"})
    (repo / "src" / "diff_sanity.py").write_text("a = 2\n", encoding="utf-8")

    await skill_prompt_eval_loop._assert_only_module_changed(
        repo, "src/diff_sanity.py"
    )  # must not raise


async def test_assert_only_module_changed_raises_on_extra_modified_file(
    tmp_path: Path,
) -> None:
    repo = _init_git_repo(
        tmp_path,
        {
            "src/diff_sanity.py": "a = 1\n",
            "tests/trust/adversarial/corpus_runner.py": "b = 1\n",
        },
    )
    (repo / "src" / "diff_sanity.py").write_text("a = 2\n", encoding="utf-8")
    (repo / "tests" / "trust" / "adversarial" / "corpus_runner.py").write_text(
        "b = 2\n", encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="tests/trust/adversarial/corpus_runner.py"):
        await skill_prompt_eval_loop._assert_only_module_changed(
            repo, "src/diff_sanity.py"
        )


async def test_assert_only_module_changed_raises_on_untracked_file(
    tmp_path: Path,
) -> None:
    repo = _init_git_repo(tmp_path, {"src/diff_sanity.py": "a = 1\n"})
    (repo / "src" / "diff_sanity.py").write_text("a = 2\n", encoding="utf-8")
    (repo / "src" / "sneaky.py").write_text("evil = True\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="src/sneaky.py"):
        await skill_prompt_eval_loop._assert_only_module_changed(
            repo, "src/diff_sanity.py"
        )


async def test_assert_only_module_changed_catches_prefix_differential_bypass(
    refine_loop_factory, tmp_path: Path
) -> None:
    """The exact exploit from the finding: a patch bundles one legit
    `a/`/`b/`-prefixed section against the allowed builder module with one
    `x/`/`y/`-prefixed section against the validation harness. `git apply`'s
    default `-p1` strips a single leading component regardless of its name,
    so both sections apply; `check_tripwires` only recognizes literal
    `a/`/`b/`, so the harness rewrite contributes zero targets and sails
    through. The changed-set assertion catches it anyway."""
    from prompt_refiner import check_tripwires

    repo = _init_git_repo(
        tmp_path,
        {
            "src/diff_sanity.py": (
                "def build_diff_sanity_prompt(**_kwargs):\n    return 'AAAA'\n"
            ),
            "tests/trust/adversarial/corpus_runner.py": "ORIGINAL\n",
        },
    )
    bypass_patch = (
        "--- a/src/diff_sanity.py\n"
        "+++ b/src/diff_sanity.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def build_diff_sanity_prompt(**_kwargs):\n"
        "-    return 'AAAA'\n"
        "+    return 'BBBB'\n"
        "--- x/tests/trust/adversarial/corpus_runner.py\n"
        "+++ y/tests/trust/adversarial/corpus_runner.py\n"
        "@@ -1 +1 @@\n"
        "-ORIGINAL\n"
        "+HIJACKED\n"
    )

    # The pre-eval tripwire scan is blind to the `x/`/`y/` section.
    assert check_tripwires(bypass_patch, "diff-sanity", repo) == []

    loop = refine_loop_factory(llm=_FakeRefineLLM(GOOD_PATCH))
    await loop._apply_patch_in_worktree(repo, bypass_patch)
    # `git apply` really did rewrite the validation harness on disk.
    assert (
        repo / "tests/trust/adversarial/corpus_runner.py"
    ).read_text() == "HIJACKED\n"

    with pytest.raises(RuntimeError, match="tests/trust/adversarial/corpus_runner.py"):
        await skill_prompt_eval_loop._assert_only_module_changed(
            repo, "src/diff_sanity.py"
        )


# ---------------------------------------------------------------------------
# Production call-site double-increment semantics (Finding 4): a case that
# drifts PASS->FAIL AND fails auto-refinement in the same tick bumps the
# repair-attempt counter twice — once in `_do_work`'s drift-regression
# bookkeeping, once more in `_try_refine`'s non-shipping-outcome bookkeeping.
# This is intended (a stuck auto-refine still walks the case toward HITL
# escalation at the same rate as a hand-fixed one) — pin it via `_do_work`,
# not by calling `_try_refine` directly.
# ---------------------------------------------------------------------------


async def test_do_work_refine_failure_double_increments_attempts(
    refine_loop_factory, monkeypatch
) -> None:
    bad = GOOD_PATCH.replace("src/diff_sanity.py", "src/pr_manager.py")
    loop = refine_loop_factory(llm=_FakeRefineLLM(bad))
    loop._pr.list_issues_by_label = AsyncMock(return_value=[])
    loop._pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    loop._state.set_skill_prompt_last_green({"accidental-deletion": "PASS"})

    async def fake_run_corpus() -> list[dict]:
        return [_drift_case()]

    monkeypatch.setattr(loop, "_run_corpus", fake_run_corpus)

    stats = await loop._do_work()

    assert stats["filed"] == 1
    # One increment from the drift-regression path, one more from
    # `_try_refine`'s tripwire (non-shipping) outcome.
    assert loop._state.get_skill_prompt_attempts("accidental-deletion") == 2


# ---------------------------------------------------------------------------
# Telemetry consumption (Task 7, spec §5) — scorecard appended to the cycle
# summary, baseline advanced for next tick, and `prompt-inefficiency` issues
# filed (deduped) when a source's cost-per-call regresses past threshold.
# ---------------------------------------------------------------------------


class _FakeTelemetry:
    """Minimal `PromptTelemetry.get_source_totals()` double — deterministic
    totals without going through the real cost-estimation/pricing pipeline."""

    def __init__(self, totals: dict[str, dict[str, int]]) -> None:
        self._totals = totals

    def get_source_totals(self) -> dict[str, dict[str, int]]:
        return self._totals


def _steady_case(case_id: str = "steady-case") -> dict[str, object]:
    return {
        "case_id": case_id,
        "skill": "diff-sanity",
        "expected_catcher": "diff-sanity",
        "status": "PASS",
    }


async def test_do_work_appends_scorecard_and_advances_baseline(
    refine_loop_factory, monkeypatch
) -> None:
    loop = refine_loop_factory()
    loop._pr.list_issues_by_label = AsyncMock(return_value=[])
    loop._pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    loop._telemetry.record(
        source="diff-sanity",
        tool="claude",
        model="sonnet",
        issue_number=1,
        pr_number=0,
        session_id="s1",
        prompt_chars=100,
        transcript_chars=50,
        duration_seconds=0.1,
        success=True,
        stats={"total_tokens": 10},
    )

    async def fake_run_corpus() -> list[dict]:
        return [_steady_case()]

    monkeypatch.setattr(loop, "_run_corpus", fake_run_corpus)

    stats = await loop._do_work()

    assert stats["efficiency_scorecard"].startswith("| skill ")
    assert "diff-sanity" in stats["efficiency_scorecard"]
    # Baseline advances to this tick's snapshot for next week's comparison.
    baseline = loop._state.get_prompt_efficiency_baseline()
    assert baseline["diff-sanity"]["inference_calls"] == 1


async def test_do_work_files_prompt_inefficiency_issue_past_threshold(
    refine_loop_factory, monkeypatch
) -> None:
    loop = refine_loop_factory()
    loop._pr.list_issues_by_label = AsyncMock(return_value=[])
    loop._pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    loop._pr.create_issue = AsyncMock(return_value=99)

    # Last week: cheap. This week: 10x cost-per-call => trend > 0.5 threshold.
    loop._state.set_prompt_efficiency_baseline(
        {
            "diff-sanity": {
                "inference_calls": 10,
                "estimated_cost_microusd": 1_000_000,
                "usage_unavailable_calls": 0,
            }
        }
    )
    loop._telemetry = _FakeTelemetry(
        {
            "diff-sanity": {
                "inference_calls": 10,
                "estimated_cost_microusd": 10_000_000,
                "usage_unavailable_calls": 0,
            }
        }
    )

    async def fake_run_corpus() -> list[dict]:
        return [_steady_case()]

    monkeypatch.setattr(loop, "_run_corpus", fake_run_corpus)

    await loop._do_work()

    loop._pr.create_issue.assert_awaited_once()
    title, _body, labels = loop._pr.create_issue.await_args.args
    assert "diff-sanity" in title
    assert "prompt-inefficiency" in labels

    # Second tick, same regressed source: dedup short-circuits, no re-file.
    loop._pr.create_issue.reset_mock()
    monkeypatch.setattr(loop, "_run_corpus", fake_run_corpus)
    await loop._do_work()
    loop._pr.create_issue.assert_not_awaited()


async def test_do_work_iterates_pick_refine_order_not_raw_corpus_order(
    refine_loop_factory, monkeypatch
) -> None:
    """Wiring check: `_do_work` must feed the drift-regression loop from
    `pick_refine_order`'s output, not the raw `_run_corpus` order."""
    loop = refine_loop_factory(llm=_FakeRefineLLM(GOOD_PATCH))
    loop._pr.list_issues_by_label = AsyncMock(return_value=[])
    loop._pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    loop._try_refine = AsyncMock(return_value="disabled")
    loop._state.set_skill_prompt_last_green({"case_a": "PASS", "case_b": "PASS"})

    async def fake_run_corpus() -> list[dict]:
        return [
            {
                "case_id": "case_a",
                "skill": "diff-sanity",
                "expected_catcher": "diff-sanity",
                "status": "FAIL",
            },
            {
                "case_id": "case_b",
                "skill": "diff-sanity",
                "expected_catcher": "diff-sanity",
                "status": "FAIL",
            },
        ]

    monkeypatch.setattr(loop, "_run_corpus", fake_run_corpus)

    processed_order: list[str] = []

    async def fake_file_drift_issue(case: dict, _was: str) -> int:
        processed_order.append(str(case["case_id"]))
        return 1

    monkeypatch.setattr(loop, "_file_drift_issue", fake_file_drift_issue)
    # Force pick_refine_order to reverse whatever list it's given, proving
    # `_do_work` iterates ITS output rather than the untouched corpus order.
    monkeypatch.setattr(
        skill_prompt_eval_loop,
        "pick_refine_order",
        lambda cases, _rows: list(reversed(cases)),
    )

    await loop._do_work()

    assert processed_order == ["case_b", "case_a"]
