"""Every prompt this runner builds.

Clustered by what breaks together: a prompt-shape change touches these and
nothing else, and _build_review_prompt_with_stats alone was a quarter of the
original file.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from base_runner import BaseRunner

if TYPE_CHECKING:
    from review_advisor import ReviewPlan

from agent_cli import build_agent_command
from human_steering import fenced_steering_guidance
from models import (
    CodeScanningAlert,
    PRInfo,
    Task,
)
from plugin_skill_registry import (
    discover_plugin_skills,
    format_plugin_skills_for_prompt,
    skills_for_phase,
)
from prompt_builder import PromptBuilder
from runner_constants import MEMORY_SUGGESTION_PROMPT

logger = logging.getLogger("hydraflow.reviewer")


class ReviewPromptMixin(BaseRunner):
    """Every prompt this runner builds."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``ReviewRunner.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------

    if TYPE_CHECKING:

        @staticmethod
        def _format_code_scanning_alerts(
            alerts: list[CodeScanningAlert],
            max_chars: int,
            *,
            repo: str = "",
            branch: str = "",
        ) -> str: ...  # provided by _context

        def _load_plan_for_review(self, issue: Task) -> str: ...  # provided by _context

        def _summarize_diff(
            self, pr_number: int, diff: str
        ) -> str: ...  # provided by _parsing

        def _summarize_issue_body(self, body: str) -> str: ...  # provided by _parsing

    async def _build_review_prompt_with_stats(
        self,
        pr: PRInfo,
        issue: Task,
        diff: str,
        precheck_context: str = "",
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
        bead_tasks: list[dict[str, object]] | None = None,
        pre_flight_plan: ReviewPlan | None = None,
        surface: str = "pr_review",
        human_guidance: str = "",
    ) -> tuple[str, dict[str, object]]:
        """Build the review prompt and pruning stats.

        ``human_guidance`` (ADR-0099 #4) is live operator steering for this
        issue; folded in fenced via :func:`fenced_steering_guidance`, which
        returns ``""`` when there is no guidance so behavior is unchanged
        for issues with the feature off or no posted guidance.
        """
        ci_enabled = self._config.max_ci_fix_attempts > 0
        test_cmd = self._config.test_command
        ui_criteria = ""
        if "ui/" in diff:
            ui_criteria = """
7. **UI-specific checks** (PR modifies frontend code):
   - DRY: No duplicated constants, types, or styles — import from `constants.js`, `types.js`, `theme.js`.
   - Responsive: Layout containers set `minWidth`; flex items handle shrinking (`minWidth: 0` or `overflow: hidden`).
   - Style consistency: Spacing uses 4px grid multiples; colors come from `theme.js`, not hardcoded values.
   - Component reuse: No new component that duplicates an existing one in `src/ui/src/components/`.
   - Shared code: New constants/types belong in centralized files, not inline.
"""

        if ci_enabled:
            verify_step = (
                "5. Do NOT run `make lint`, `make test`, or `make quality` — "
                "CI will verify these automatically after review."
            )
            fix_verify = "2. Do NOT run tests locally — CI will verify after push."
        elif self._config.use_quality_gate_in_review:
            verify_step = (
                "5. Run `make quality` to verify everything passes "
                "(full suite: lint, types, security, tests)."
            )
            fix_verify = (
                "2. Run `make quality` (do not use file-targeted subsets — "
                "architecture tests only run under the full suite)."
            )
        else:
            verify_step = (
                f"5. Run `make lint` and `{test_cmd}` to verify everything passes."
            )
            fix_verify = f"2. Run `make lint` and `{test_cmd}`."

        diff_context = self._summarize_diff(pr.number, diff)

        min_findings = self._config.min_review_findings

        memory_section = await self._inject_memory(
            query_context=f"{issue.title}\n{(issue.body or '')[:200]}",
        )

        # Runtime log injection
        log_section = ""
        from log_context import load_runtime_logs  # noqa: PLC0415

        logs = load_runtime_logs(self._config)
        if logs:
            log_section = f"\n\n## Recent Application Logs\n\n```\n{logs}\n```"

        # Code scanning alerts injection
        scanning_section = ""
        if code_scanning_alerts:
            formatted = self._format_code_scanning_alerts(
                code_scanning_alerts,
                self._config.max_code_scanning_chars,
                repo=self._config.repo,
                branch=pr.branch,
            )
            if formatted:
                scanning_section = f"\n\n## Code Scanning Alerts\n\n{formatted}"

        # Per-bead review section
        bead_section = ""
        if bead_tasks:
            bead_lines: list[str] = []
            for bt in bead_tasks:
                bead_lines.append(
                    f"- **Bead #{bt.get('id', '?')}** ({bt.get('phase', '?')}): "
                    f"status={bt.get('status', 'unknown')}, "
                    f"files={bt.get('files', 'N/A')}, "
                    f"tests={bt.get('tests', 'N/A')}"
                )
            bead_section = (
                "\n\n## Per-Bead Review\n\n"
                "Verify each bead's acceptance criteria are met:\n"
                + "\n".join(bead_lines)
                + "\n\nFor each bead, confirm:\n"
                "- Files listed are present in the diff\n"
                "- Tests match the behavioral specs\n"
                "- No extra scope beyond the bead's goal\n"
            )

        issue_body = self._summarize_issue_body(issue.body)

        # Plan compliance section — inject structured plan for scope comparison
        plan_section = ""
        plan_text = self._load_plan_for_review(issue)
        if plan_text:
            plan_section = (
                "\n\n## Implementation Plan (for scope comparison)\n\n"
                "Use this plan to verify that the PR implements what was planned. "
                "Flag files modified that aren't in the plan (scope creep) and "
                "planned files that are missing from the diff (incomplete).\n\n"
                f"{plan_text}"
            )

        # Spec-match section for product-track issues
        spec_section = ""
        if any(
            "Selected Product Direction" in c or "DECOMPOSITION REQUIRED" in c
            for c in (issue.comments or [])
        ):
            from spec_match import build_reviewer_spec_section  # noqa: PLC0415

            spec_section = build_reviewer_spec_section(issue)

        # Pre-flight plan section (advisor-pattern T18). When the upstream
        # PreFlightAdvisor produced a ReviewPlan, render it as a focus rubric
        # so the executor's review prioritizes the listed focus_areas and
        # rubric items. Empty string when no plan was produced (kill-switched,
        # composite trigger said "no", or advisor degraded to None).
        from review_advisor import (  # noqa: PLC0415
            build_mid_flight_prompt,
            build_surface_config,
            format_pre_flight_for_prompt,
        )

        pre_flight_section = format_pre_flight_for_prompt(pre_flight_plan)

        # Mid-flight consult section (advisor-pattern T21). When the surface
        # has mid-flight enabled (kill-switch chain open), document the
        # consult_advisor Task tool so the executor knows to call it on
        # judgment calls. The ``surface`` kwarg threaded through ``review()``
        # picks the surface config (T24.7 — was hardcoded "pr_review" prior
        # to Phase 4 multi-surface wiring; default keeps back-compat).
        # Returns None when mid-flight is disabled; coerce to "" so the
        # f-string concatenation below stays branch-free.
        mid_flight_section = (
            build_mid_flight_prompt(build_surface_config(surface)) or ""
        )

        prompt = f"""You are reviewing PR #{pr.number} which implements issue #{issue.id}.

## Issue: {issue.title}

{issue_body}{plan_section}{memory_section}{log_section}{scanning_section}{bead_section}{spec_section}{pre_flight_section}{mid_flight_section}

## Precheck Context

{precheck_context or "No low-tier precheck context provided."}

## PR Diff

{diff_context}

## Review Instructions

1. Evaluate four dimensions: **scope**, correctness, completeness, and quality.
2. **Scope check (mandatory first step):** Flag any file or change unrelated to the issue or missing from the implementation plan (if provided above). Unrelated test, docs, or config changes are scope creep — reject them. Never add tests for ADR markdown content.
2a. **Verify findings against live code (mandatory):** Grep or read the live file to confirm each finding exists in the current codebase before reporting it — a stale artifact from a prior fix is not a finding.
3. You MUST find at least {min_findings} issues across all categories. If you find fewer, re-examine the code more carefully.
4. If you genuinely find fewer than {min_findings} issues, include THOROUGH_REVIEW_COMPLETE:
```
THOROUGH_REVIEW_COMPLETE
Scope: No issues — <justification>
Correctness: No issues — <justification>
Completeness: No issues — <justification>
Quality: No issues — <justification>
```
{verify_step}
6. Run project audits on changed code:
   - Code quality (SRP, type hints, naming, complexity) and test quality (3As structure, factories, edge cases)
   - **Security** — injection, unsafe deserialization, crypto misuse, auth/authz gaps, secret/credential exposure, unsafe `subprocess`/shell
   - **Test-value standards (merge gate)** — request changes for:
     - Skipped, xfailed, commented-out, or placeholder tests in active coverage — record deferred work through the active issue/PR workflow instead
     - Unit tests that bypass documented factories or world-building helpers (for HydraFlow: `ConfigFactory`, `TaskFactory`, `make_pr_manager`, MockWorld helpers)
     - Integration tests that mock behavior-changing collaborators or assert only mock call shape — wire real business logic; mock only external boundaries that cannot run in the test environment
     - MockWorld scenarios that replace FakeGitHub/Fake* side effects with raw `AsyncMock`/`MagicMock` call-count assertions instead of asserting state through `world.<fake>`
   - **Test coverage audit** — tests cover the specific issue requirements (not just helpers); failure/error paths have explicit tests; every new public function is called from production code (flag tested-but-never-invoked dead code); new branches have test cases
   - Flag redundant guard conditions in if/elif chains — hoist the shared guard
   - Merge-artifact check: duplicate Pydantic Field definitions, duplicate function parameters, or duplicate keyword arguments (concurrent PRs adding the same field, merged sequentially)
   - **Architectural drift** — check the diff for:
     - **Layer jumps:** files under `domain/`, `core/`, `models/`, `entities/`, or `ports/` must not import from `adapters/`, `adapter/`, `infrastructure/`, `infra/`, `io/`, or `gateways/` (outer → inner is fine; inner → outer is drift)
     - **Misplaced I/O:** new direct use of I/O primitives (`subprocess`, `socket`, `httpx`, `requests`, `urllib`, `boto3`, `sqlalchemy`, `pymongo`, `redis`, `kafka`, raw `open()`, file reads/writes) under `domain/`, `core/`, `models/`, `entities/`, or in files named `*_model.py`, `*_entity.py`, `*_value*.py`, `*_rules.py` — the I/O belongs in an adapter
     - **God-file creep:** files that grew significantly (many new imports, or >~50% line-count increase) and now orchestrate unrelated concerns
     - **Escape hatch:** if the repo has no recognisable layering convention (no `domain/`, `core/`, `adapters/`, or similar signal directories or filename patterns), skip this bullet entirely — do not invent violations
   - **HydraFlow principles (ADR-0044)** — flag as findings:
     - **MockWorld scenario coverage:** new cross-phase / orchestrator / runner behaviour without a release-gating scenario under `tests/scenarios/` using `MockWorld` fakes — unit tests alone don't cover the loop
     - **BDD-flavour test naming:** tests named after the function (`test_create_widget`) instead of the behaviour (`test_create_widget_with_duplicate_name_raises_integrity_error`)
     - **Port compliance:** new direct use of `subprocess`, `gh`, or `git` CLI, or direct GitHub API calls, outside the adapter layer — route through `PRPort`, `IssueStorePort`, or `WorkspacePort`
     - **One responsibility per file:** large additions that give an already-large file a second concern — prefer a new file
     - **Escape hatch:** skip this bullet if the repo isn't HydraFlow (no `tests/scenarios/`, `ports.py`, or similar seams)
{ui_criteria}
## If Issues Found

If you find issues that you can fix:
1. Make the fixes directly.
{fix_verify}
3. Commit with message: "review: fix <description> (PR #{pr.number})"
3a. **Self-review before pushing (mandatory):** Run `git diff HEAD~N..HEAD` and verify: (a) no unintended files changed, (b) no debug code or TODO comments remain, (c) the fix's failure mode is not broader than the issue it resolves.
4. **Post-commit verification (mandatory):** After each commit, run `git diff --stat HEAD~1` and verify your commit by confirming every intended file appears in the stat output. If a file is missing, your commit did NOT actually change it — go back and fix it. Especially critical for scope-creep removal commits; for factory migrations, grep for the old pattern (e.g., `TaskFactory.create()`) in test files that were supposed to be reverted.

## Findings Format

List findings in this compact schema:
`[SEVERITY] file[:line] - issue - expected fix`
Use `HIGH|MEDIUM|LOW`.

## Required Output

End your response with EXACTLY one of these verdict lines:
- VERDICT: APPROVE
- VERDICT: REQUEST_CHANGES
- VERDICT: COMMENT

Then a brief summary on the next line starting with "SUMMARY: ".

Example:
VERDICT: APPROVE
SUMMARY: Implementation looks good, tests are comprehensive, all checks pass.

{MEMORY_SUGGESTION_PROMPT.format(context="review")}"""
        plugin_skills_section = format_plugin_skills_for_prompt(
            skills_for_phase(
                "reviewer",
                discover_plugin_skills(self._config.required_plugins),
                self._config.phase_skills,
            )
        )
        if plugin_skills_section:
            prompt = f"{prompt}\n\n{plugin_skills_section}"

        prompt += fenced_steering_guidance(human_guidance)

        review_builder = PromptBuilder()
        review_builder.record_context("Issue body", issue.body or "", issue_body)
        review_builder.record_context("Diff", diff, diff_context)
        return prompt, review_builder.build_stats()

    def _build_review_fix_prompt(
        self,
        pr: PRInfo,
        issue: Task,
        review_summary: str,
        advisor_transcript: str | None = None,
        suggested_fix_direction: str | None = None,
    ) -> str:
        """Build a prompt to fix issues identified during review.

        When ``advisor_transcript`` is provided, an "Advisor disagreement"
        section is appended so the executor can address what the advisor
        flagged.
        """
        test_cmd = self._config.test_command
        advisor_section = ""
        if advisor_transcript:
            advisor_section = (
                "\n\n## Advisor disagreement (you must address this)\n\n"
                f"{advisor_transcript}"
            )
        if suggested_fix_direction:
            advisor_section += (
                f"\n\n## Suggested direction\n\n{suggested_fix_direction}"
            )
        if self._config.use_quality_gate_in_review:
            verify_cmd_step = (
                "3. Run `make quality` to verify your fixes pass (do not use "
                "file-targeted subsets — architecture tests only run under the "
                "full suite)."
            )
        else:
            verify_cmd_step = (
                f"3. Run `make lint` and `{test_cmd}` to verify your fixes pass."
            )
        return f"""You are fixing review findings on PR #{pr.number} (issue #{issue.id}: {issue.title}).

## Review Feedback

{review_summary}{advisor_section}

## Instructions

1. Read the review feedback above carefully.
2. Fix every issue identified by the reviewer.
{verify_cmd_step}
4. Commit fixes with message: "review-fix: address review feedback (PR #{pr.number})"
4a. **Self-review before pushing:** Run `git diff HEAD~N..HEAD` and confirm: no unintended files changed, no debug code remains, the fix's own failure mode is not worse than the original finding.
5. **Post-commit verification:** After each commit, run `git diff --stat HEAD~1` and verify your commit by confirming that every intended file appears in the stat output. If a file is missing, your commit did NOT actually change it — go back and fix it.
6. Do NOT introduce new features or refactor beyond what the review requested.

## Required Output

End your response with EXACTLY one of these verdict lines:
- VERDICT: APPROVE   (if all review findings are fixed)
- VERDICT: REQUEST_CHANGES  (if you could not fix them)

Then a brief summary on the next line starting with "SUMMARY: ".
"""

    def _build_ci_fix_prompt(
        self,
        pr: PRInfo,
        issue: Task,
        failure_summary: str,
        attempt: int,
        ci_logs: str = "",
        code_scanning_alerts: list[CodeScanningAlert] | None = None,
    ) -> tuple[str, dict[str, object]]:
        """Build a focused prompt for fixing CI failures."""
        raw_ci_logs = ci_logs or ""
        compact_ci_logs = raw_ci_logs
        if len(compact_ci_logs) > self._config.max_ci_log_prompt_chars:
            compact_ci_logs = (
                compact_ci_logs[: self._config.max_ci_log_prompt_chars]
                + f"\n\n[CI logs truncated from {len(raw_ci_logs):,} chars]"
            )

        ci_logs_section = ""
        if compact_ci_logs:
            ci_logs_section = (
                f"\n\n## Full CI Failure Logs\n\n```\n{compact_ci_logs}\n```"
            )

        scanning_section = ""
        if code_scanning_alerts:
            formatted = self._format_code_scanning_alerts(
                code_scanning_alerts,
                self._config.max_code_scanning_chars,
                repo=self._config.repo,
                branch=pr.branch,
            )
            if formatted:
                scanning_section = f"\n\n## Code Scanning Alerts\n\n{formatted}"

        test_cmd = self._config.test_command
        if self._config.use_quality_gate_in_review:
            ci_verify_step = (
                "3. Run `make quality` to verify locally (full suite: lint, "
                "types, security, tests — do not use file-targeted subsets)."
            )
        else:
            ci_verify_step = f"3. Run `make lint` and `{test_cmd}` to verify locally."
        prompt = f"""You are fixing CI failures on PR #{pr.number} (issue #{issue.id}: {issue.title}).

## CI Failure Summary

{failure_summary}{ci_logs_section}{scanning_section}

## Fix Attempt {attempt}

1. Read the failing CI output above.
2. Fix the root causes — do NOT skip or disable tests.
{ci_verify_step}
4. Commit fixes with message: "ci-fix: <description> (PR #{pr.number})"
5. **Post-commit verification:** After each commit, run `git diff --stat HEAD~1` and verify your commit by confirming that every intended file appears in the stat output. If a file is missing, your commit did NOT actually change it — go back and fix it.

## Required Output

End your response with EXACTLY one of these verdict lines:
- VERDICT: APPROVE   (if CI failures are fixed)
- VERDICT: REQUEST_CHANGES  (if you could not fix them)

Then a brief summary on the next line starting with "SUMMARY: ".
"""
        ci_builder = PromptBuilder()
        ci_builder.record_context(
            "CI failure summary", failure_summary, failure_summary
        )
        ci_builder.record_context("CI logs", raw_ci_logs, compact_ci_logs)
        return prompt, ci_builder.build_stats()

    def _build_precheck_prompt(self, pr: PRInfo, issue: Task, diff: str) -> str:
        max_diff = min(len(diff), 3000, self._config.max_review_diff_chars)
        diff_snippet = diff[:max_diff]
        return f"""Run a compact review precheck for PR #{pr.number} (issue #{issue.id}).

Goal:
- estimate risk and confidence
- list top findings (max 5)
- recommend whether debug escalation is needed

Return EXACTLY:
PRECHECK_RISK: low|medium|high
PRECHECK_CONFIDENCE: <0.0-1.0>
PRECHECK_ESCALATE: yes|no
PRECHECK_SUMMARY: <one line>

Issue title: {issue.title}
Diff snippet:
```diff
{diff_snippet}
```
"""

    def _build_command(self, _worktree_path: Path | None = None) -> list[str]:
        """Construct the review CLI invocation.

        The working directory is set via ``cwd`` in the subprocess call,
        not via a CLI flag.
        """
        return build_agent_command(
            tool=self._config.review_tool,
            model=self._config.review_model,
        )
