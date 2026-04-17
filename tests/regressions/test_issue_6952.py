"""Regression test for issue #6952.

Bug: ``DiagnosticRunner.fix()`` re-raises a narrow set of system errors
(``PermissionError``, ``KeyboardInterrupt``, ``SystemExit``, ``MemoryError``)
but catches ``AuthenticationError`` and ``CreditExhaustedError`` in its
catch-all ``except Exception``.  When the diagnostic agent hits a credential
or credit failure, the caller receives ``(False, "Fix agent crashed")``
instead of seeing the auth/credit error propagate.  This burns a retry
against the attempt cap and can incorrectly escalate issues to HITL.

Expected behaviour after fix:
  - ``AuthenticationError`` raised during ``fix()`` propagates to the caller.
  - ``CreditExhaustedError`` raised during ``fix()`` propagates to the caller.
  - Both ``diagnose()`` and ``fix()`` treat these the same as
    ``PermissionError`` — i.e. re-raise, never swallow.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from models import DiagnosisResult, Severity
from subprocess_util import AuthenticationError, CreditExhaustedError


@pytest.fixture
def runner():
    from diagnostic_runner import DiagnosticRunner

    config = MagicMock()
    config.repo_root = "/tmp/repo"
    config.implementation_tool = "claude"
    config.model = "claude-opus-4-5"
    bus = MagicMock()
    return DiagnosticRunner(config=config, event_bus=bus)


@pytest.fixture
def sample_diagnosis():
    return DiagnosisResult(
        root_cause="Missing null check",
        severity=Severity.P2_FUNCTIONAL,
        fixable=True,
        fix_plan="Add guard clause",
        human_guidance="Review the fix",
        affected_files=["src/foo.py"],
    )


class TestFixPropagatesAuthErrors:
    """Issue #6952 — AuthenticationError must not be swallowed by fix()."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6952 — fix not yet landed", strict=False)
    async def test_fix_propagates_authentication_error(
        self, runner, sample_diagnosis, monkeypatch
    ) -> None:
        """When ``_execute`` raises ``AuthenticationError``, ``fix()`` must
        let it propagate instead of returning ``(False, "Fix agent crashed")``.

        RED today — the except-Exception block at diagnostic_runner.py:187
        catches ``AuthenticationError`` (a ``RuntimeError`` subclass).
        """

        async def raise_auth(*_args, **_kwargs):
            raise AuthenticationError("GitHub token expired")

        monkeypatch.setattr(runner, "_execute", raise_auth)

        with pytest.raises(AuthenticationError, match="GitHub token expired"):
            await runner.fix(
                issue_number=6952,
                issue_title="Auth failure test",
                issue_body="body",
                diagnosis=sample_diagnosis,
                wt_path="/tmp/worktree",
            )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6952 — fix not yet landed", strict=False)
    async def test_fix_propagates_credit_exhausted_error(
        self, runner, sample_diagnosis, monkeypatch
    ) -> None:
        """When ``_execute`` raises ``CreditExhaustedError``, ``fix()`` must
        let it propagate instead of returning ``(False, "Fix agent crashed")``.

        RED today — same catch-all swallows ``CreditExhaustedError``.
        """

        async def raise_credits(*_args, **_kwargs):
            raise CreditExhaustedError("API credits exhausted")

        monkeypatch.setattr(runner, "_execute", raise_credits)

        with pytest.raises(CreditExhaustedError, match="API credits exhausted"):
            await runner.fix(
                issue_number=6952,
                issue_title="Credit failure test",
                issue_body="body",
                diagnosis=sample_diagnosis,
                wt_path="/tmp/worktree",
            )


class TestDiagnosePropagatesAuthErrors:
    """Issue #6952 — diagnose() has the same pattern; verify it's also broken."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6952 — fix not yet landed", strict=False)
    async def test_diagnose_propagates_authentication_error(
        self, runner, monkeypatch
    ) -> None:
        """``diagnose()`` also has ``except Exception`` that swallows auth errors.

        RED today — diagnostic_runner.py:121-124 has the same bug.
        """
        from models import EscalationContext

        ctx = EscalationContext(cause="CI failed", origin_phase="review")

        async def raise_auth(*_args, **_kwargs):
            raise AuthenticationError("GitHub token expired")

        monkeypatch.setattr(runner, "_execute", raise_auth)

        with pytest.raises(AuthenticationError, match="GitHub token expired"):
            await runner.diagnose(
                issue_number=6952,
                issue_title="Auth failure test",
                issue_body="body",
                context=ctx,
            )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6952 — fix not yet landed", strict=False)
    async def test_diagnose_propagates_credit_exhausted_error(
        self, runner, monkeypatch
    ) -> None:
        """``diagnose()`` also swallows ``CreditExhaustedError``.

        RED today — same catch-all pattern.
        """
        from models import EscalationContext

        ctx = EscalationContext(cause="CI failed", origin_phase="review")

        async def raise_credits(*_args, **_kwargs):
            raise CreditExhaustedError("API credits exhausted")

        monkeypatch.setattr(runner, "_execute", raise_credits)

        with pytest.raises(CreditExhaustedError, match="API credits exhausted"):
            await runner.diagnose(
                issue_number=6952,
                issue_title="Credit failure test",
                issue_body="body",
                context=ctx,
            )


class TestFixStillCatchesGenericErrors:
    """Guard rail — generic exceptions should still be caught (GREEN today)."""

    @pytest.mark.asyncio
    async def test_fix_catches_generic_runtime_error(
        self, runner, sample_diagnosis, monkeypatch
    ) -> None:
        """A plain ``RuntimeError`` should still return ``(False, "Fix agent crashed")``.

        GREEN today — ensures the fix doesn't over-correct by removing the
        catch-all entirely.
        """

        async def raise_generic(*_args, **_kwargs):
            raise RuntimeError("something unrelated broke")

        monkeypatch.setattr(runner, "_execute", raise_generic)

        success, transcript = await runner.fix(
            issue_number=6952,
            issue_title="Generic error test",
            issue_body="body",
            diagnosis=sample_diagnosis,
            wt_path="/tmp/worktree",
        )
        assert success is False
        assert transcript == "Fix agent crashed"
