"""The CI-timeout repair path and the diagnostics only it needs.

A timeout is not a failing assertion: there is no error message to hand an
agent, so this path first has to MANUFACTURE evidence — isolate the tests
that hang, name the language of the worktree — before a fix prompt can say
anything specific. That is why it is separate from ``_resolve``: the other
causes arrive with their evidence already attached.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from exception_classify import reraise_on_credit_or_bug

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agent import AgentRunner
    from config import HydraFlowConfig
    from merge_conflict_resolver import MergeConflictResolver
    from models import GitHubIssue
    from phase_utils import MemorySuggester
    from ports import WorkspacePort
    from state import StateTracker
    from troubleshooting_store import (
        TroubleshootingPatternStore,
    )


logger = logging.getLogger("hydraflow.pr_unsticker")


class PRUnstickerTimeoutMixin:
    """The CI-timeout repair path and the diagnostics only it needs."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``PRUnsticker.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------
    _agents: AgentRunner
    _config: HydraFlowConfig
    _resolver: MergeConflictResolver | None
    _state: StateTracker
    _suggest_memory: MemorySuggester
    _troubleshooting_store: TroubleshootingPatternStore | None
    _workspaces: WorkspacePort

    if TYPE_CHECKING:

        def _build_ci_timeout_fix_prompt(
            self,
            issue: GitHubIssue,
            pr_url: str,
            cause: str,
            isolation_output: str,
            *,
            learned_patterns_section: str = "",
        ) -> tuple[str, dict[str, object]]: ...  # provided by _prompts

        async def _persist_troubleshooting_pattern(
            self,
            transcript: str,
            issue_number: int,
            language: str,
            *,
            issue_labels: Sequence[str] = (),
        ) -> None: ...  # provided by _reflection

    async def _resolve_ci_timeout(
        self,
        issue_number: int,
        issue: GitHubIssue,
        wt_path: Path,
        branch: str,
        pr_url: str,
        pr_number: int = 0,
    ) -> bool:
        """Rebase on main, isolate the hanging test, and run agent to fix it.

        Retries up to ``max_ci_timeout_fix_attempts`` times before giving up.
        """
        max_attempts = self._config.max_ci_timeout_fix_attempts

        # Read path: load learned patterns from store
        learned_section = ""
        language = "general"
        if self._troubleshooting_store is not None:
            language = self._detect_language(wt_path)
            patterns = self._troubleshooting_store.load_patterns(
                language=language,
                limit=10,
            )
            if patterns:
                from troubleshooting_store import format_patterns_for_prompt

                learned_section = format_patterns_for_prompt(
                    patterns,
                    max_chars=self._config.max_troubleshooting_prompt_chars,
                )

        for attempt in range(1, max_attempts + 1):
            # Rebase on main
            clean = await self._workspaces.start_merge_main(wt_path, branch)
            if not clean:
                await self._workspaces.abort_merge(wt_path)

            # Isolate which test hangs
            isolation_output = await self._isolate_hanging_tests(wt_path)

            cause_str = self._state.get_hitl_cause(issue_number) or ""
            prompt, prompt_stats = self._build_ci_timeout_fix_prompt(
                issue,
                pr_url,
                cause_str,
                isolation_output,
                learned_patterns_section=learned_section,
            )

            try:
                cmd = self._agents.build_command(wt_path)
                transcript = await self._agents.execute(
                    cmd,
                    prompt,
                    wt_path,
                    {"issue": issue_number, "source": "pr_unsticker"},
                    issue_labels=issue.labels,
                    telemetry_stats=prompt_stats,
                )
                if self._resolver is not None:
                    self._resolver.save_conflict_transcript(
                        pr_number,
                        issue_number,
                        attempt,
                        transcript,
                        source="unsticker",
                    )

                await self._suggest_memory(
                    transcript, "pr_unsticker", f"issue #{issue_number}"
                )

                verify = await self._agents.verify_result(wt_path, branch)
                if verify.passed:
                    # Write path: persist pattern from transcript
                    await self._persist_troubleshooting_pattern(
                        transcript,
                        issue_number,
                        language,
                        issue_labels=issue.labels,
                    )
                    return True

                logger.warning(
                    "CI timeout fix attempt %d/%d failed for issue #%d: %s",
                    attempt,
                    max_attempts,
                    issue_number,
                    verify.summary[:200] if verify.summary else "",
                )
            except (OSError, RuntimeError, ValueError, asyncio.CancelledError) as exc:
                # CreditExhaustedError subclasses RuntimeError — reraise it (plus
                # auth/likely-bug) so the loop pauses instead of burning the
                # remaining timeout-fix attempts against an exhausted signal.
                reraise_on_credit_or_bug(exc)
                logger.error(
                    "Unsticker CI timeout agent failed for issue #%d (attempt %d): %s",
                    issue_number,
                    attempt,
                    exc,
                )

        return False

    def _detect_language(self, wt_path: Path) -> str:
        """Detect the project language from the worktree path."""
        try:
            from polyglot_prep import detect_prep_stack

            return detect_prep_stack(wt_path)
        except (RuntimeError, OSError, ImportError) as exc:
            logger.warning(
                "Falling back to 'general' language classification for %s: %s",
                wt_path,
                exc,
                exc_info=True,
            )
            return "general"

    async def _isolate_hanging_tests(self, wt_path: Path) -> str:
        """Run the project's test command with a short subprocess timeout.

        Uses the configured ``test_command`` so it works for any language.
        Sets ``PYTHONPATH`` for Python projects (harmless for others).

        Returns a string describing test output before the timeout hit,
        or an error message if isolation itself failed.
        """
        import os
        import shlex

        src_dir = str(wt_path / "src")
        existing = os.environ.get("PYTHONPATH", "")
        env = {
            **os.environ,
            "PYTHONPATH": f"{src_dir}{os.pathsep}{existing}" if existing else src_dir,
        }

        test_cmd = self._config.test_command
        cmd = shlex.split(test_cmd) if test_cmd else ["make", "test"]

        try:
            result = await self._agents._runner.run_simple(
                cmd,
                cwd=str(wt_path),
                timeout=120.0,
                env=env,
            )
            return (
                f"Test command `{test_cmd}` completed (rc={result.returncode}):\n"
                f"{result.stdout[-2000:]}"
            )
        except TimeoutError:
            return (
                f"Test command `{test_cmd}` timed out after 120s — "
                "tests are hanging. Check the test output for the last test "
                "that started running before the timeout."
            )
        except (RuntimeError, OSError) as exc:
            return f"Test isolation failed ({test_cmd}): {exc}"
