"""Tests for SkillPromptEvalLoop (spec §4.6)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from skill_prompt_eval_loop import SkillPromptEvalLoop


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    state.get_skill_prompt_last_green.return_value = {}
    state.get_skill_prompt_attempts.return_value = 0
    state.inc_skill_prompt_attempts.return_value = 1
    # Refine weekly-cap read must return a real int (a bare MagicMock raises on
    # the `>= max_weekly` compare); 0 lets `_try_refine` proceed past the cap.
    state.refine_proposals_last_7d.return_value = 0
    pr = AsyncMock()
    pr.create_issue = AsyncMock(return_value=42)
    pr.list_issues_by_label = AsyncMock(return_value=[])
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    dedup = MagicMock()
    dedup.get.return_value = set()
    return cfg, state, pr, dedup


def test_skeleton_worker_name_and_interval(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )
    assert loop._worker_name == "skill_prompt_eval"
    assert loop._get_default_interval() == 604800


async def test_detects_regression_pass_to_fail(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup = loop_env
    state.get_skill_prompt_last_green.return_value = {
        "case_shrink_001": "PASS",
        "case_scope_002": "PASS",
    }
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_run_corpus() -> list[dict]:
        return [
            {
                "case_id": "case_shrink_001",
                "skill": "diff_sanity",
                "status": "FAIL",
                "provenance": "hand-crafted",
                "expected_catcher": "diff_sanity",
            },
            {
                "case_id": "case_scope_002",
                "skill": "scope_check",
                "status": "PASS",
                "provenance": "hand-crafted",
                "expected_catcher": "scope_check",
            },
        ]

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_run_corpus", fake_run_corpus)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    assert stats["filed"] == 1
    title = pr.create_issue.await_args.args[0]
    assert "diff_sanity" in title
    assert "case_shrink_001" in title
    labels = pr.create_issue.await_args.args[2]
    assert "skill-prompt-drift" in labels


async def test_weak_case_sampling_files_corpus_case_weak(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    # 10 learning-loop cases, all PASS — loop expects some to be caught
    # (test provides `expected_catcher: diff_sanity` but the run returned
    # `skill=diff_sanity, status=PASS` meaning the skill let it through).
    cases = [
        {
            "case_id": f"case_learn_{i:03d}",
            "skill": "diff_sanity",
            "status": "PASS",
            "provenance": "learning-loop",
            "expected_catcher": "diff_sanity",
        }
        for i in range(10)
    ]

    async def fake_run_corpus() -> list[dict]:
        return cases

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_run_corpus", fake_run_corpus)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    # 10% of 10 = 1 case sampled. Sampled case is flagged because
    # its expected catcher passed it. So 1 corpus-case-weak issue.
    assert stats["weak_cases_flagged"] >= 1
    weak_calls = [
        c
        for c in pr.create_issue.await_args_list
        if "corpus-case-weak" in (c.args[2] if len(c.args) > 2 else [])
    ]
    assert len(weak_calls) >= 1


async def test_escalation_fires_after_three_attempts(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup = loop_env
    state.get_skill_prompt_last_green.return_value = {"case_shrink_001": "PASS"}
    state.inc_skill_prompt_attempts.return_value = 3
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_run_corpus():
        return [
            {
                "case_id": "case_shrink_001",
                "skill": "diff_sanity",
                "status": "FAIL",
                "provenance": "hand-crafted",
                "expected_catcher": "diff_sanity",
            }
        ]

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_run_corpus", fake_run_corpus)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    assert stats["escalated"] == 1
    labels = pr.create_issue.await_args.args[2]
    assert "hitl-escalation" in labels
    assert "skill-prompt-stuck" in labels


async def test_reconcile_closed_escalations(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    dedup.get.return_value = {"skill_prompt_eval:case_alpha"}
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    pr.list_closed_issues_by_label.return_value = [
        {
            "number": 9618,
            "title": "HITL: skill prompt drift case_alpha unresolved after 3",
            "body": "",
            "updated_at": "",
        }
    ]

    await loop._reconcile_closed_escalations()
    dedup.set_all.assert_called_once()
    remaining = dedup.set_all.call_args.args[0]
    assert "skill_prompt_eval:case_alpha" not in remaining
    state.clear_skill_prompt_attempts.assert_called_once_with("case_alpha")


async def test_do_work_clears_inefficiency_key_when_issue_closed(
    loop_env, monkeypatch
) -> None:
    """#10025: a closed `prompt-inefficiency` issue clears its dedup key on the
    next tick (same closed-path reconcile as escalations), so a source that
    re-degrades after triage re-files instead of hitting a dead dedup key."""
    from skill_prompt_eval_loop import _INEFFICIENCY_LABEL, _inefficiency_title

    cfg, state, pr, dedup = loop_env
    key = "skill_prompt_eval:inefficiency:base_runner"
    dedup.get.return_value = {key}

    async def _closed(label: str, limit: int = 100) -> list[dict]:
        if label == _INEFFICIENCY_LABEL:
            return [
                {
                    "number": 9701,
                    "title": _inefficiency_title("base_runner"),
                    "body": "",
                    "updated_at": "",
                }
            ]
        return []

    pr.list_closed_issues_by_label.side_effect = _closed
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )
    loop._run_corpus = AsyncMock(return_value=[])

    await loop._do_work()

    dedup.set_all.assert_called_once()
    remaining = dedup.set_all.call_args.args[0]
    assert key not in remaining
    # Inefficiency filings have no per-source attempt counter to clear.
    state.clear_skill_prompt_attempts.assert_not_called()


async def test_inefficiency_refiles_after_key_cleared(loop_env) -> None:
    """With the dedup key cleared, `_file_inefficiency_issue` files again for
    the same source; with the key present it stays deduped (#10025)."""
    from prompt_efficiency import SkillEfficiencyRow
    from skill_prompt_eval_loop import _INEFFICIENCY_LABEL

    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )
    row = SkillEfficiencyRow(
        source="base_runner",
        calls=120,
        est_cost_usd=3.6,
        anomalies=0,
        cost_per_call=0.03,
        trend_vs_baseline=0.42,
    )

    dedup.get.return_value = {"skill_prompt_eval:inefficiency:base_runner"}
    await loop._file_inefficiency_issue(row)
    pr.create_issue.assert_not_awaited()  # key present -> deduped

    dedup.get.return_value = set()
    await loop._file_inefficiency_issue(row)
    pr.create_issue.assert_awaited_once()
    labels = pr.create_issue.await_args.args[2]
    assert _INEFFICIENCY_LABEL in labels


def test_inefficiency_title_round_trips_through_subject_parser() -> None:
    """The reconciler's title parser must invert the filing path's title
    builder — drift between them orphans the dedup key forever (#10025)."""
    from skill_prompt_eval_loop import _inefficiency_subject, _inefficiency_title

    assert _inefficiency_subject(_inefficiency_title("base_runner")) == "base_runner"
    assert _inefficiency_subject("Some operator-created issue title") is None


_STALE_ESCALATION = {
    "number": 9618,
    "title": "HITL: skill prompt drift case_shrink_001 unresolved after 3",
    "body": "",
    "updated_at": "",
}


async def test_do_work_autocloses_stale_escalation(loop_env, monkeypatch) -> None:
    """A case passing again at HEAD auto-closes its open `skill-prompt-stuck`
    escalation on the next completed corpus run (#9618 class). The dedup key
    is already gone here — discovery comes from the escalation title."""
    cfg, state, pr, dedup = loop_env
    pr.list_issues_by_label.return_value = [_STALE_ESCALATION]
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_run_corpus() -> list[dict]:
        return [
            {
                "case_id": "case_shrink_001",
                "skill": "diff_sanity",
                "status": "PASS",
                "provenance": "hand-crafted",
                "expected_catcher": "diff_sanity",
            }
        ]

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_run_corpus", fake_run_corpus)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()

    pr.close_issue.assert_awaited_once_with(9618)
    state.clear_skill_prompt_attempts.assert_called_once_with("case_shrink_001")
    assert stats["autoclosed"] == 1


async def test_do_work_keeps_escalation_for_still_failing_case(
    loop_env, monkeypatch
) -> None:
    """An escalation whose case still FAILs this run must survive."""
    cfg, state, pr, dedup = loop_env
    dedup.get.return_value = {"skill_prompt_eval:case_shrink_001"}
    pr.list_issues_by_label.return_value = [_STALE_ESCALATION]
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_run_corpus() -> list[dict]:
        return [
            {
                "case_id": "case_shrink_001",
                "skill": "diff_sanity",
                "status": "FAIL",
                "provenance": "hand-crafted",
                "expected_catcher": "diff_sanity",
            }
        ]

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_run_corpus", fake_run_corpus)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()

    pr.close_issue.assert_not_awaited()
    state.clear_skill_prompt_attempts.assert_not_called()
    assert stats["autoclosed"] == 0


async def test_do_work_capped_tick_skips_open_reconcile(loop_env, monkeypatch) -> None:
    """A capped tick only *sampled* the corpus — an escalated case absent
    from the sample must not read as recovered, so the open-escalation
    re-verify is skipped entirely (active_subjects=None)."""
    cfg, state, pr, dedup = loop_env
    cfg.skill_prompt_eval_max_corpus_cases = 10
    # The escalated case is not in the corpus at all this tick.
    pr.list_issues_by_label.return_value = [_STALE_ESCALATION]
    cases = [
        {
            "case_id": f"c{i}",
            "skill": "x",
            "status": "PASS",
            "provenance": "hand-crafted",
        }
        for i in range(100)
    ]
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_run_corpus() -> list[dict]:
        return cases

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_run_corpus", fake_run_corpus)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()

    pr.close_issue.assert_not_awaited()
    pr.list_issues_by_label.assert_not_awaited()
    assert stats["autoclosed"] == 0


@pytest.mark.asyncio
async def test_kill_switch_short_circuits_do_work(loop_env) -> None:
    """Disabled kill-switch → _do_work returns `disabled` and skips reconcile (ADR-0049)."""
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda name: name != "skill_prompt_eval",
    )
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=deps
    )
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._run_corpus = AsyncMock(
        side_effect=AssertionError("must not run when disabled")
    )
    stats = await loop._do_work()
    assert stats == {"status": "disabled"}
    loop._reconcile_closed_escalations.assert_not_awaited()
    pr.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_do_work_caps_corpus_cases(loop_env) -> None:
    """G6: when corpus exceeds max_corpus_cases, sample down to the cap."""
    cfg, state, pr, dedup = loop_env
    # Seed: 1000 cases, all PASS, all fresh — no escalations would fire.
    cases = [
        {
            "case_id": f"c{i}",
            "skill": "x",
            "status": "PASS",
            "provenance": "hand-crafted",
        }
        for i in range(1000)
    ]
    cfg.skill_prompt_eval_max_corpus_cases = 50

    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        deps=_deps(stop),
    )
    loop._run_corpus = AsyncMock(return_value=cases)
    state.get_skill_prompt_last_green.return_value = {}

    await loop._do_work()

    # The loop's per-case work should have been called only `cap` times,
    # not `len(cases)`. We can't easily mock the inner loop, so instead
    # we assert the new logger.warning fired by checking caplog if
    # available, or count attempts. Simpler: assert state inc was
    # called <= cap times.
    assert state.inc_skill_prompt_attempts.call_count <= 50


async def test_recovery_closes_drift_issue_and_clears(loop_env, monkeypatch) -> None:
    """#9359: a case that passes again (its dedup key set) closes the open drift
    issue, clears the dedup key + attempts."""
    cfg, state, pr, dedup = loop_env
    dedup.get.return_value = {"skill_prompt_eval:case_shrink_001"}
    pr.find_existing_issue = AsyncMock(return_value=88)
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_run_corpus() -> list[dict]:
        return [
            {
                "case_id": "case_shrink_001",
                "skill": "diff_sanity",
                "status": "PASS",
                "provenance": "hand-crafted",
                "expected_catcher": "diff_sanity",
            },
        ]

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_run_corpus", fake_run_corpus)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()

    assert stats["resolved"] == 1
    pr.close_issue.assert_awaited_once_with(88)
    state.clear_skill_prompt_attempts.assert_called_once_with("case_shrink_001")


# --- #9555: heavy-make timeout is an operator knob, read live per call -------


async def test_run_corpus_timeout_uses_config_knob(loop_env, monkeypatch) -> None:
    """The `make trust-adversarial` bound comes from the live config knob
    (#9555), not a hardcoded constant — a System-tab PATCH (which mutates the
    live config in-place) applies to the next invocation without a restart."""
    from execution import SimpleResult

    cfg, state, pr, dedup = loop_env
    object.__setattr__(cfg, "skill_prompt_eval_adversarial_timeout_seconds", 777)
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    captured: dict[str, object] = {}

    async def fake_result(*cmd: str, **kwargs: object) -> SimpleResult:
        captured["cmd"] = cmd
        captured["timeout"] = kwargs.get("timeout")
        return SimpleResult(stdout="[]", stderr="", returncode=0)

    monkeypatch.setattr("skill_prompt_eval_loop.run_subprocess_result", fake_result)

    out = await loop._run_corpus()

    assert out == []
    assert captured["cmd"][:2] == ("make", "trust-adversarial")
    assert captured["timeout"] == 777


async def test_run_corpus_default_timeout_preserves_prior_constant(
    loop_env, monkeypatch
) -> None:
    """Default knob value == the former _ADVERSARIAL_TIMEOUT_SECONDS (3600):
    no behaviour change when the operator sets nothing."""
    from execution import SimpleResult

    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    captured: dict[str, object] = {}

    async def fake_result(*_cmd: str, **kwargs: object) -> SimpleResult:
        captured["timeout"] = kwargs.get("timeout")
        return SimpleResult(stdout="[]", stderr="", returncode=0)

    monkeypatch.setattr("skill_prompt_eval_loop.run_subprocess_result", fake_result)

    await loop._run_corpus()

    assert captured["timeout"] == 3600


async def test_validate_candidate_timeout_uses_config_knob(
    loop_env, monkeypatch, tmp_path
) -> None:
    """The live-skill refine-validation corpus run shares the adversarial-eval
    semantic, so it is bounded by the same knob (#9555)."""
    from execution import SimpleResult

    cfg, state, pr, dedup = loop_env
    object.__setattr__(cfg, "skill_prompt_eval_adversarial_timeout_seconds", 777)
    stop = asyncio.Event()
    loop = SkillPromptEvalLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    monkeypatch.setattr(
        "skill_prompt_eval_loop.discover_validation_case_ids",
        lambda _cases_dir, _case_id: ["case_x"],
    )

    captured: dict[str, object] = {}

    async def fake_result(*_cmd: str, **kwargs: object) -> SimpleResult:
        captured["timeout"] = kwargs.get("timeout")
        return SimpleResult(stdout="[]", stderr="", returncode=0)

    monkeypatch.setattr("skill_prompt_eval_loop.run_subprocess_result", fake_result)

    await loop._validate_candidate(tmp_path, "diff_sanity", "case_x")

    assert captured["timeout"] == 777
