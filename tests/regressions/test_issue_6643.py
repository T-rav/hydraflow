"""Regression tests for issue #6643.

The visual gate must not silently pass when no semantic visual validation
service is configured. The default implementation fails closed; tests that need
a passing visual service must mock ``_invoke_visual_pipeline`` explicitly.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from config import HydraFlowConfig
from tests.conftest import PRInfoFactory, ReviewResultFactory, TaskFactory
from tests.helpers import ConfigFactory, make_review_phase


class TestIssue6643VisualPipelineFailsClosed:
    """The visual gate is fail-closed unless a pipeline is explicitly wired."""

    @pytest.mark.asyncio
    async def test_invoke_visual_pipeline_is_not_a_stub(
        self, config: HydraFlowConfig
    ) -> None:
        """The unconfigured default must never hardcode a pass verdict."""
        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            repo_root=config.repo_root,
            workspace_base=config.workspace_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        verdict, _artifacts, reason = await phase._invoke_visual_pipeline(
            pr, issue, worker_id=0
        )

        assert verdict != "pass", (
            "_invoke_visual_pipeline must fail closed until a semantic visual "
            "validation service is configured."
        )
        assert reason == (
            "visual gate is enabled but no semantic visual validation service "
            "is configured"
        )
        assert _artifacts == {}

    @pytest.mark.asyncio
    async def test_visual_gate_can_reject_a_pr(self, config: HydraFlowConfig) -> None:
        """An unconfigured visual gate blocks merge instead of granting pass."""
        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            visual_gate_bypass=False,
            repo_root=config.repo_root,
            workspace_base=config.workspace_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        phase._bus.publish = AsyncMock()
        phase._prs.post_pr_comment = AsyncMock()
        phase._escalate_to_hitl = AsyncMock()

        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        ok = await phase.check_visual_gate(pr, issue, result, worker_id=0)

        assert ok is False
        assert result.visual_passed is False
        phase._escalate_to_hitl.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stub_warning_should_not_exist_in_production(
        self, config: HydraFlowConfig
    ) -> None:
        """The default path logs a concrete configuration error, not a stub warning."""
        import io
        import logging

        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            repo_root=config.repo_root,
            workspace_base=config.workspace_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        # Capture warnings from the review_phase logger.
        handler = logging.StreamHandler(io.StringIO())
        handler.setLevel(logging.WARNING)
        logger = logging.getLogger("hydraflow.review_phase")
        logger.addHandler(handler)
        try:
            await phase._invoke_visual_pipeline(pr, issue, worker_id=0)
            log_output = handler.stream.getvalue()
            assert "stub" not in log_output.lower(), (
                "_invoke_visual_pipeline logs a WARNING that it is a stub. "
                "A production feature flag must not gate placeholder code."
            )
        finally:
            logger.removeHandler(handler)
