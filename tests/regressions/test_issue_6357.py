"""Regression test for issue #6357.

Bug: _run_pre_merge_spec_check catches all exceptions and returns True,
meaning any error (network, auth, credit-exhaustion, agent crash) silently
approves the merge — the spec-match safety gate fails open.

Expected behaviour after fix:
  - Non-retryable errors (CreditExhaustedError, AuthenticationError) must
    propagate rather than being swallowed.
  - Even for "soft" failures, the fail-open path must be observable (counter,
    Sentry breadcrumb, etc.).

These tests intentionally assert the *correct* behaviour, so they are RED
against the current (buggy) code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.conftest import TaskFactory
from tests.helpers import make_review_phase


def _product_track_task(**kwargs):
    """Create a Task that passes _is_product_track_pr (has shape comment)."""
    return TaskFactory.create(
        comments=["Selected Product Direction: build widget"],
        **kwargs,
    )


class TestSpecMatchFailOpen:
    """Issue #6357 — spec-match check should not auto-approve on exception."""

    @pytest.mark.asyncio
    async def test_credit_exhausted_error_is_not_swallowed(self, config) -> None:
        """CreditExhaustedError must propagate — not silently approve merge."""
        phase = make_review_phase(config)
        task = _product_track_task()

        credit_error = RuntimeError("CreditExhaustedError: no credits remaining")

        # The deferred imports inside _run_pre_merge_spec_check import from
        # spec_match and agent_cli modules.  We patch spec_match functions at
        # module level and make the _execute call raise.
        with patch.dict("sys.modules", {
            "spec_match": MagicMock(
                build_self_review_prompt=MagicMock(return_value="prompt"),
                extract_spec_match=MagicMock(return_value={"verdict": "MATCH"}),
            ),
            "agent_cli": MagicMock(
                build_agent_command=MagicMock(return_value=["echo", "test"]),
            ),
        }):
            phase._reviewers._execute = AsyncMock(side_effect=credit_error)

            with pytest.raises(RuntimeError, match="CreditExhaustedError"):
                await phase._run_pre_merge_spec_check(task, "diff text")

    @pytest.mark.asyncio
    async def test_authentication_error_is_not_swallowed(self, config) -> None:
        """AuthenticationError must propagate — not silently approve merge."""
        phase = make_review_phase(config)
        task = _product_track_task()

        auth_error = PermissionError("AuthenticationError: invalid API key")

        with patch.dict("sys.modules", {
            "spec_match": MagicMock(
                build_self_review_prompt=MagicMock(return_value="prompt"),
                extract_spec_match=MagicMock(return_value={"verdict": "MATCH"}),
            ),
            "agent_cli": MagicMock(
                build_agent_command=MagicMock(return_value=["echo", "test"]),
            ),
        }):
            phase._reviewers._execute = AsyncMock(side_effect=auth_error)

            with pytest.raises(PermissionError, match="AuthenticationError"):
                await phase._run_pre_merge_spec_check(task, "diff text")

    @pytest.mark.asyncio
    async def test_generic_exception_does_not_return_true(self, config) -> None:
        """Even soft failures should not return True (approve).

        The current code returns True on any exception — the fix should
        return False (block merge) so the failure is visible, or at least
        not silently approve.
        """
        phase = make_review_phase(config)
        task = _product_track_task()

        with patch.dict("sys.modules", {
            "spec_match": MagicMock(
                build_self_review_prompt=MagicMock(return_value="prompt"),
                extract_spec_match=MagicMock(return_value={"verdict": "MATCH"}),
            ),
            "agent_cli": MagicMock(
                build_agent_command=MagicMock(return_value=["echo", "test"]),
            ),
        }):
            phase._reviewers._execute = AsyncMock(
                side_effect=RuntimeError("agent crashed")
            )

            result = await phase._run_pre_merge_spec_check(task, "diff text")

            # After the fix, a crashed spec check must NOT approve merge.
            assert result is False, (
                "Spec-match check returned True (approve) after an exception — "
                "this is the fail-open bug from issue #6357"
            )
