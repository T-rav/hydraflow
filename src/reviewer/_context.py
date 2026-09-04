"""Evidence gathered before the reviewer runs.

The plan it is judged against, the precheck context, and the code-scanning
alerts folded into the prompt.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from base_runner import BaseRunner
from change_chain_reader import read_plan
from models import (
    CodeScanningAlert,
    PRInfo,
    Task,
)
from plan_constants import PLAN_COMMENT_HEADING
from precheck import run_precheck_context
from prompt_builder import PromptBuilder

logger = logging.getLogger("hydraflow.reviewer")


class ReviewContextMixin(BaseRunner):
    """Evidence gathered before the reviewer runs."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``ReviewRunner.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------

    if TYPE_CHECKING:

        def _build_precheck_prompt(
            self, pr: PRInfo, issue: Task, diff: str
        ) -> str: ...  # provided by _prompts

    def _load_plan_for_review(self, issue: Task) -> str:
        """Load the implementation plan for scope comparison during review.

        Checks issue comments for :data:`plan_constants.PLAN_COMMENT_HEADING`,
        then falls back to the saved plan file at
        ``.hydraflow/plans/issue-N.md``. Returns the plan text or empty string
        if not found.

        The heading is the shared constant rather than a literal spelled here,
        because #11543 gave the plan a second reader — a Fable reviewer's
        canonical evidence — and "both presets judge the same artefact" holds
        only while both find it by the same rule.
        """
        # Check issue comments first
        for comment in issue.comments or []:
            if PLAN_COMMENT_HEADING in comment:
                return comment

        # Fallback to the plan cache, then the committed chain. No
        # worktree in scope here, so the cache is the fresher signal —
        # see read_plan for why repo_root is consulted last.
        return read_plan(self._config, issue.id).strip()

    async def _run_precheck_context(
        self, pr: PRInfo, issue: Task, diff: str, worktree_path: Path
    ) -> str:
        prompt = self._build_precheck_prompt(pr, issue, diff)

        async def execute(cmd: list[str], p: str) -> str:
            precheck_builder = PromptBuilder()
            precheck_builder.record_context("Precheck", (issue.body or "") + diff, p)
            return await self._execute(
                cmd,
                p,
                worktree_path,
                {"pr": pr.number, "issue": issue.id, "source": "reviewer"},
                telemetry_stats=precheck_builder.build_stats(),
                issue_labels=issue.tags,
            )

        return await run_precheck_context(
            config=self._config,
            prompt=prompt,
            diff=diff,
            execute=execute,
            debug_message="DEBUG MODE: Focus on root causes and concrete risky files.",
            logger=logger,
        )

    @staticmethod
    def _format_code_scanning_alerts(
        alerts: list[CodeScanningAlert],
        max_chars: int,
        *,
        repo: str = "",
        branch: str = "",
    ) -> str:
        """Format code scanning alerts for prompt injection.

        Each alert is rendered as a single line:
        ``- [SEVERITY] path:line — rule (message)``

        When the formatted output exceeds *max_chars*, it is truncated and
        a note with the ``gh`` command to fetch the full set is appended.
        """
        if not alerts:
            return ""

        lines: list[str] = []
        for alert in alerts:
            severity = (alert.security_severity or alert.severity or "unknown").upper()
            path = alert.path or "?"
            line = alert.start_line if alert.start_line is not None else "?"
            rule = alert.rule or "unknown rule"
            message = alert.message or ""
            entry = f"- [{severity}] {path}:{line} — {rule}"
            if message:
                entry += f" ({message})"
            lines.append(entry)

        formatted = "\n".join(lines)
        if len(formatted) <= max_chars:
            return formatted

        # Truncate and add instructions to fetch the full set
        truncated = formatted[:max_chars]
        shown = truncated.count("\n") + 1
        total = len(alerts)
        gh_cmd = f"gh api repos/{repo}/code-scanning/alerts --field ref={branch} --field state=open"
        note = (
            f"\n\n[Showing {shown} of {total} alerts — truncated at {max_chars:,} chars. "
            f"Run `{gh_cmd}` for the full set.]"
        )
        return truncated + note
