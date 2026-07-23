"""Regression: CH-6 gate pin covered 5 of 12 runner modules (#10000).

``_RUNNER_EXECUTE_MODULES`` was a hand-maintained tuple listing only
``agent.py, planner.py, research_runner.py, reviewer.py, hitl_runner.py`` —
other BaseRunner subclass modules (diagnostic_runner, discover_runner,
shape_runner, bug_reproducer, plan_reviewer, triage) bypassed
the ``issue_labels=`` pin entirely, so a ``data-class:regulated-*`` issue
label did NOT elevate the prompt gate for their spawns — exactly the omission
the pin was written to make "structurally impossible to reintroduce" (#9734
review finding 1).

Pins:
- The runner-module list is DERIVED from the BaseRunner subclass set via AST,
  so it can never rot again — a synthetic new subclass module with an
  unlabeled ``self._execute`` call is flagged the moment it exists.
- Every previously-bypassed module is in the derived list.
- DiagnosticRunner threads ``issue_labels`` all the way to
  ``base_runner.gate_prompt`` for both the diagnose and fix spawns.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from models import EscalationContext
from tests.helpers import ConfigFactory
from tests.test_prompt_gate_completeness import (
    _base_runner_modules,
    _unlabeled_execute_calls,
)

# Every BaseRunner subclass module at the time of the fix. The seven entries
# after hitl_runner.py are the ones the hand-maintained tuple missed.
_ALL_RUNNER_MODULES = {
    "agent.py",
    "planner.py",
    "research_runner.py",
    "reviewer.py",
    "hitl_runner.py",
    "diagnostic_runner.py",
    "discover_runner.py",
    "shape_runner.py",
    "bug_reproducer.py",
    "plan_reviewer.py",
    "triage.py",
}

_SYNTHETIC_UNLABELED = """\
from base_runner import BaseRunner


class SneakyRunner(BaseRunner):
    async def run(self, cmd, prompt, cwd):
        return await self._execute(cmd, prompt, cwd, {"issue": 1})
"""

_SYNTHETIC_LABELED = """\
from base_runner import BaseRunner


class PoliteRunner(BaseRunner):
    async def run(self, cmd, prompt, cwd, task):
        return await self._execute(
            cmd, prompt, cwd, {"issue": task.id}, issue_labels=task.tags
        )
"""


class TestDerivedRunnerList:
    def test_derived_list_covers_every_baserunner_subclass_module(self) -> None:
        """All 12 runner modules — including the 7 the old tuple missed."""
        assert set(_base_runner_modules()) >= _ALL_RUNNER_MODULES

    def test_synthetic_runner_omitting_kwarg_is_flagged(self, tmp_path: Path) -> None:
        """A brand-new BaseRunner subclass module cannot dodge the pin."""
        module = tmp_path / "sneaky_runner.py"
        module.write_text(_SYNTHETIC_UNLABELED)

        derived = _base_runner_modules(tmp_path)
        assert "sneaky_runner.py" in derived, (
            "AST derivation failed to pick up a new BaseRunner subclass "
            "module — the completeness pin would silently skip it."
        )
        offenders = _unlabeled_execute_calls(module, "sneaky_runner.py")
        assert offenders == ["sneaky_runner.py:6"], (
            "The unlabeled self._execute call in a new runner module must be "
            f"flagged; got {offenders}."
        )

    def test_synthetic_runner_passing_kwarg_is_clean(self, tmp_path: Path) -> None:
        module = tmp_path / "polite_runner.py"
        module.write_text(_SYNTHETIC_LABELED)

        assert "polite_runner.py" in _base_runner_modules(tmp_path)
        assert _unlabeled_execute_calls(module, "polite_runner.py") == []

    def test_non_runner_module_is_not_in_derived_list(self, tmp_path: Path) -> None:
        """Only BaseRunner subclass modules are pinned — no false positives."""
        module = tmp_path / "plain_helper.py"
        module.write_text("class Helper:\n    pass\n")

        assert "plain_helper.py" not in _base_runner_modules(tmp_path)


_LABELS = ("data-class:regulated-phi", "bug")


def _make_runner(tmp_path: Path):
    from diagnostic_runner import DiagnosticRunner

    config = ConfigFactory.create(repo_root=tmp_path)
    bus = MagicMock()
    bus.current_session_id = "sess-test"
    return DiagnosticRunner(config, bus)


class TestDiagnosticRunnerLabelThreading:
    @pytest.mark.asyncio
    async def test_diagnose_threads_issue_labels_to_gate_prompt(
        self, tmp_path: Path
    ) -> None:
        runner = _make_runner(tmp_path)
        ctx = EscalationContext(cause="CI failed", origin_phase="review")
        gated = MagicMock()
        gated.prompt = "gated prompt"

        with (
            patch("base_runner.gate_prompt", return_value=gated) as gate,
            patch(
                "base_runner.stream_claude_process",
                new_callable=AsyncMock,
                return_value="out",
            ),
        ):
            await runner.diagnose(42, "Bug", "Fix it", ctx, issue_labels=_LABELS)

        assert gate.call_args is not None, "gate_prompt was never consulted"
        assert tuple(gate.call_args.kwargs["issue_labels"]) == _LABELS

    @pytest.mark.asyncio
    async def test_fix_threads_issue_labels_to_gate_prompt(
        self, tmp_path: Path
    ) -> None:
        from models import DiagnosisResult, Severity

        runner = _make_runner(tmp_path)
        diagnosis = DiagnosisResult(
            root_cause="Missing import",
            severity=Severity.P2_FUNCTIONAL,
            fixable=True,
            fix_plan="Add the import",
            human_guidance="Trivial",
        )
        gated = MagicMock()
        gated.prompt = "gated prompt"
        verify = MagicMock()
        verify.passed = True
        runner._verify_quality = AsyncMock(return_value=verify)  # type: ignore[method-assign]

        with (
            patch("base_runner.gate_prompt", return_value=gated) as gate,
            patch(
                "base_runner.stream_claude_process",
                new_callable=AsyncMock,
                return_value="out",
            ),
        ):
            await runner.fix(
                42, "Bug", "Fix it", diagnosis, str(tmp_path), issue_labels=_LABELS
            )

        assert gate.call_args is not None, "gate_prompt was never consulted"
        assert tuple(gate.call_args.kwargs["issue_labels"]) == _LABELS
