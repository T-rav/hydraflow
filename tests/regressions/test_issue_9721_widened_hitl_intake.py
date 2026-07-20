"""Regression pins for #9721 — widened AutoAgentPreflightLoop HITL intake.

Before #9721 the loop polled only ``hitl-escalation``, so the highest-volume
human touchpoints — plain ``hydraflow-hitl`` issues produced when
ImplementPhase exhausts its attempt cap or bails on quality-gate/zero-diff
failures — went straight to a human with no autonomous attempt (contradicting
dark-factory §1). These pins guarantee:

1. An idle pipeline-origin ``hydraflow-hitl`` issue is intercepted and
   claimed (``hydraflow-hitl-autofix``) before any spawn.
2. The human-handoff race guards hold: ``hydraflow-hitl-active`` and
   ``human-required`` issues are never intercepted.
3. The ``auto_agent_hitl_intake_enabled`` kill-switch restores the old
   single-label poll, and its env-table default matches the Field default.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from auto_agent_preflight_loop import AutoAgentPreflightLoop
from config import _ENV_BOOL_OVERRIDES, HydraFlowConfig
from preflight.agent import PreflightSpawn
from tests.helpers import make_bg_loop_deps


def _issue(number: int, label_names: list[str]) -> dict:
    return {
        "number": number,
        "body": "b",
        "labels": [{"name": name} for name in label_names],
    }


def _make_loop(tmp_path: Path, label_map: dict[str, list[dict]]):
    deps = make_bg_loop_deps(tmp_path)
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=0)
    state.bump_auto_agent_attempts = MagicMock(return_value=1)
    state.get_auto_agent_daily_spend = MagicMock(return_value=0.0)
    state.add_auto_agent_daily_spend = MagicMock(return_value=0.0)
    state.get_escalation_context = MagicMock(return_value=None)
    state.get_hitl_origin = MagicMock(return_value="hydraflow-ready")
    pr = AsyncMock()
    pr.list_closed_issues_by_label = AsyncMock(return_value=[])
    pr.list_issue_comments = AsyncMock(return_value=[])
    pr.add_labels = AsyncMock(return_value=None)
    pr.remove_label = AsyncMock(return_value=None)
    pr.post_comment = AsyncMock(return_value=None)
    pr.swap_pipeline_labels = AsyncMock(return_value=None)

    async def _route(label: str) -> list[dict]:
        return label_map.get(label, [])

    pr.list_issues_by_label = AsyncMock(side_effect=_route)
    audit = MagicMock()
    audit.append = MagicMock()
    audit.daily_spend = MagicMock(return_value=0.0)
    audit.entries_for_issue = MagicMock(return_value=[])
    loop = AutoAgentPreflightLoop(
        config=deps.config,
        state=state,
        pr_manager=pr,
        wiki_store=None,
        audit_store=audit,
        deps=deps.loop_deps,
    )
    return loop, state, pr


@pytest.mark.asyncio
async def test_idle_cap_exhausted_hitl_issue_gets_autonomous_attempt(
    tmp_path: Path,
) -> None:
    """The headline regression: a plain hydraflow-hitl issue (no
    hitl-escalation label) is claimed and auto-attempted instead of sitting
    in the human queue untouched."""
    loop, _state, pr = _make_loop(
        tmp_path, {"hydraflow-hitl": [_issue(5, ["hydraflow-hitl"])]}
    )
    spawned: list[str] = []

    def _builder(issue: int):
        async def _spawn(prompt: str, worktree_path: str) -> PreflightSpawn:
            spawned.append(prompt)
            return PreflightSpawn(
                process=None,
                output_text=(
                    "<status>resolved</status><pr_url>https://x/pr/9</pr_url>"
                    "<confidence>high</confidence><diagnosis>fixed</diagnosis>"
                ),
                cost_usd=0.1,
                tokens=10,
                crashed=False,
            )

        return _spawn

    loop._build_spawn_fn = _builder

    result = await loop._do_work()

    assert result["issues_processed"] == 1
    assert result["result_status"] == "resolved"
    assert len(spawned) == 1
    pr.swap_pipeline_labels.assert_any_await(5, "hydraflow-hitl-autofix")


@pytest.mark.asyncio
async def test_race_guards_never_intercept_active_or_human_required(
    tmp_path: Path,
) -> None:
    loop, _state, pr = _make_loop(
        tmp_path,
        {
            "hydraflow-hitl": [
                _issue(1, ["hydraflow-hitl", "hydraflow-hitl-active"]),
                _issue(2, ["hydraflow-hitl", "human-required"]),
            ]
        },
    )
    result = await loop._do_work()
    assert result == {"status": "ok", "issues_processed": 0}
    pr.swap_pipeline_labels.assert_not_awaited()


@pytest.mark.asyncio
async def test_kill_switch_restores_single_label_poll(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYDRAFLOW_AUTO_AGENT_HITL_INTAKE_ENABLED", "false")
    loop, _state, pr = _make_loop(
        tmp_path, {"hydraflow-hitl": [_issue(5, ["hydraflow-hitl"])]}
    )
    result = await loop._do_work()
    assert result == {"status": "ok", "issues_processed": 0}
    polled = [c.args[0] for c in pr.list_issues_by_label.await_args_list]
    assert polled == ["hitl-escalation"]


def test_intake_flag_default_true_and_env_table_consistent() -> None:
    field_default = HydraFlowConfig().auto_agent_hitl_intake_enabled
    assert field_default is True
    table = {attr: default for attr, _env, default in _ENV_BOOL_OVERRIDES}
    assert "auto_agent_hitl_intake_enabled" in table
    assert table["auto_agent_hitl_intake_enabled"] == field_default
