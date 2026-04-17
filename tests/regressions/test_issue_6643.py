"""Regression test for issue #6643.

Bug: ``visual_gate_enabled`` is a production feature flag in ``HydraFlowConfig``
that gates ``ReviewPhase.check_visual_gate()``.  The method it gates —
``_invoke_visual_pipeline()`` — is an explicitly documented placeholder stub
that *always* returns ``("pass", {}, "visual validation passed")``.

If ``visual_gate_enabled=True`` in any environment, the visual gate is silently
non-functional: every PR passes visual validation regardless of actual visual
state.  This is stale-feature-flag rot — the flag is plumbed through config,
tests, and logic, but the underlying service integration was never built.

These tests will FAIL (RED) against the current code because the stub always
returns ``"pass"`` — the gate can never reject a PR on visual grounds.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from config import HydraFlowConfig
from tests.conftest import PRInfoFactory, ReviewResultFactory, TaskFactory
from tests.helpers import ConfigFactory, make_review_phase


class TestIssue6643StubVisualPipelineAlwaysPasses:
    """_invoke_visual_pipeline is a stub that always returns 'pass', making
    the visual gate non-functional when enabled."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6643 — fix not yet landed", strict=False)
    async def test_invoke_visual_pipeline_is_not_a_stub(
        self, config: HydraFlowConfig
    ) -> None:
        """_invoke_visual_pipeline must perform real validation, not return a
        hardcoded 'pass' verdict.

        Currently FAILS because the method is a placeholder stub (line 1572)
        that always returns ("pass", {}, "visual validation passed") regardless
        of the PR content.
        """
        cfg = ConfigFactory.create(
            visual_gate_enabled=True,
            repo_root=config.repo_root,
            workspace_base=config.workspace_base,
            state_file=config.state_file,
        )
        phase = make_review_phase(cfg, default_mocks=True)
        pr = PRInfoFactory.create()
        issue = TaskFactory.create()

        verdict, _artifacts, _reason = await phase._invoke_visual_pipeline(
            pr, issue, worker_id=0
        )

        # A real implementation should contact an external service.  A stub that
        # unconditionally returns "pass" means the gate is non-functional.
        assert verdict != "pass", (
            "_invoke_visual_pipeline is a placeholder stub that always returns 'pass'. "
            "The visual gate is non-functional — it cannot reject any PR."
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6643 — fix not yet landed", strict=False)
    async def test_visual_gate_can_reject_a_pr(self, config: HydraFlowConfig) -> None:
        """When visual_gate_enabled=True and the pipeline is not mocked,
        check_visual_gate must be capable of returning False (blocking merge).

        Currently FAILS because the stub always returns "pass", so the gate
        always returns True — it can never block a merge.
        """
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

        pr = PRInfoFactory.create()
        issue = TaskFactory.create()
        result = ReviewResultFactory.create()

        # Call check_visual_gate WITHOUT mocking _invoke_visual_pipeline.
        # If the pipeline were real, some PRs would fail.  With the stub,
        # this always returns True.
        await phase.check_visual_gate(pr, issue, result, worker_id=0)

        # The stub makes this impossible — the gate never blocks.
        # A non-stub implementation could return False for failing PRs.
        # We assert that the gate is *capable* of returning a non-pass verdict
        # by checking that the underlying pipeline doesn't hardcode "pass".
        verdict, _, _ = await phase._invoke_visual_pipeline(pr, issue, worker_id=0)
        assert verdict != "pass", (
            "visual gate is enabled but _invoke_visual_pipeline is a stub "
            "that always returns 'pass' — the gate provides false assurance "
            "that visual validation is running"
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6643 — fix not yet landed", strict=False)
    async def test_stub_warning_should_not_exist_in_production(
        self, config: HydraFlowConfig
    ) -> None:
        """The stub logs a WARNING about being a placeholder.  A production
        feature flag must not gate code that warns it's unfinished.

        Currently FAILS because the stub contains the warning log.
        """
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
