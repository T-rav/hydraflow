"""Regression: an untargeted runtime idles instead of crashlooping (#11786).

`config.py` promises this in as many words when `HYDRAFLOW_GITHUB_REPO` is
unset:

    "the triage/plan/implement/review/HITL loops will idle ... (The checkout's
     own remote is 'T-rav/hydraflow', which is NOT targeted automatically.)"

It did not idle. Measured on a clean factory boot, 2026-08-30:

    00:39  Starting runtime for 'hydraflow'
    00:39  HydraFlow starting — repo= label=hydraflow-ready workers=3
    00:39  Repo sanitized — fetched staging, orphan branches pruned
    00:39  ERROR Runtime exited: RuntimeError: PRManager: repo is not
           configured or invalid ('') — refusing to mutate GitHub
    00:40  Starting runtime for 'hydraflow'        <-- ~25s later
    00:40  ERROR Runtime exited: (identical)

`run()` calls `prs.ensure_labels_exist()` during bootstrap; `_assert_repo`
raises on the empty slug; nothing catches it, so the runtime dies and is
restarted forever. The dashboard reported `status: idle` throughout, which is
the part that makes this expensive to notice — a boot-looping factory and a
quiet one are indistinguishable from the outside.

The `PRManager` guard is CORRECT and stays: refusing to mutate GitHub against
an unconfigured slug is fail-closed and right. The bug is that the pipeline
reached it at all.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config import HydraFlowConfig


def _orchestrator(tmp_path: Path, repo: str):
    """A real HydraFlowOrchestrator over a mocked service graph.

    Constructs the ACTUAL object rather than re-deriving the gate expression:
    a test that recomputes `pipeline_enabled and bool(config.repo)` itself
    passes with the fix reverted, which is no test at all.
    """
    config = HydraFlowConfig(
        repo=repo,
        repo_root=tmp_path / "repo",
        data_root=tmp_path / "data",
        workspace_base=tmp_path / "worktrees",
    )
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    (tmp_path / "worktrees").mkdir(parents=True, exist_ok=True)

    with patch("orchestrator.build_services") as mock_build:
        svc = MagicMock()
        for attr in ("planners", "agents", "reviewers", "hitl_runner"):
            runner = MagicMock()
            runner._active_procs = set()
            runner.active_count = 0
            setattr(svc, attr, runner)
        svc.store = MagicMock()
        svc.store.get_active_issues = MagicMock(return_value={})
        svc.workspaces = AsyncMock()
        svc.prs = AsyncMock()
        svc.implementer = MagicMock()
        svc.implementer.active_issues = set()
        svc.reviewer = MagicMock()
        svc.reviewer.active_issues = set()
        svc.hitl_phase = MagicMock()
        svc.hitl_phase.active_hitl_issues = set()
        mock_build.return_value = svc

        from orchestrator import HydraFlowOrchestrator

        return HydraFlowOrchestrator(config)


def test_an_untargeted_orchestrator_closes_the_pipeline_gate(tmp_path: Path) -> None:
    orch = _orchestrator(tmp_path, repo="")

    assert orch.pipeline_enabled is False, (
        "an orchestrator with no repo left the pipeline gate OPEN; bootstrap "
        "will call ensure_labels_exist(), PRManager will refuse the empty "
        "slug, and the runtime will crashloop (#11786)"
    )


def test_a_targeted_orchestrator_keeps_the_gate_open(tmp_path: Path) -> None:
    """Anti-vacuity: a gate wired permanently shut would 'fix' the crashloop
    by disabling the factory, and the test above would still pass."""
    orch = _orchestrator(tmp_path, repo="T-rav/hydraflow")

    assert orch.pipeline_enabled is True


def test_the_prmanager_guard_still_refuses_an_empty_slug() -> None:
    """The backstop must remain. This regression is about not REACHING it."""
    from pr_manager import PRManager

    mgr = PRManager.__new__(PRManager)
    mgr._repo = ""  # noqa: SLF001

    with pytest.raises(RuntimeError, match="refusing to mutate GitHub"):
        mgr._assert_repo()  # noqa: SLF001
