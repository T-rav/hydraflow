"""Implement-prompt assembly for ``AgentRunner``.

Extracted VERBATIM from ``src/agent.py`` (god-class decomposition,
Refs #11547) as a mixin.

One concern: rendering the prompt the implementation agent runs — the main
builder, the ADR-0044 TDD subagent variant, and the two spec-derived sections
that only appear for product-track issues.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from base_runner import BaseRunner
from human_steering import fenced_steering_guidance
from models import (
    Task,
)
from plugin_skill_registry import (
    discover_plugin_skills,
    format_plugin_skills_for_prompt,
    skills_for_phase,
)
from prompt_builder import PromptBuilder
from runner_constants import MEMORY_SUGGESTION_PROMPT
from skill_registry import (
    discover_tools,
    format_skills_for_prompt,
    format_tools_for_prompt,
    get_skills,
)
from task_graph import extract_phases, has_task_graph, topological_sort
from untrusted_text import UNTRUSTED_DATA_PREAMBLE, fence_untrusted

logger = logging.getLogger("hydraflow.agent")


class AgentPromptMixin(BaseRunner):
    """Implement-prompt assembly for ``AgentRunner``.

    Inherits ``BaseRunner``: these slices call ``self._execute`` /
    ``self._build_command`` and one delegates to ``super()._verify_quality``,
    so the base has to sit in the MIXIN's own MRO, not only in
    ``AgentRunner``'s. It also keeps the runner-scoped gates enumerating every
    file that holds a spawn site.
    """

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``AgentRunner.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------

    if TYPE_CHECKING:

        @staticmethod
        def _build_self_check_checklist(
            escalations: list[dict[str, str | int | list[str]]],
        ) -> str: ...  # provided by _runner

        @staticmethod
        def _extract_plan_comment(
            comments: list[str],
        ) -> tuple[str, list[str]]: ...  # provided by _runner

        def _get_escalation_data(
            self,
        ) -> list[dict[str, str | int | list[str]]]: ...  # provided by _context

        def _get_review_feedback_section(self) -> str: ...  # provided by _context

        def _load_plan_fallback(
            self, issue_number: int
        ) -> str: ...  # provided by _plan

        def _summarize_for_prompt(
            self, text: str, max_chars: int, label: str
        ) -> str: ...  # provided by _context

        def _truncate_comment_for_prompt(
            self, text: str
        ) -> str: ...  # provided by _context

    @staticmethod
    def _build_spec_match_check(issue: Task) -> str:
        """Build spec-match check guidance for pre-quality review."""
        has_spec = any(
            "Selected Product Direction" in c or "DECOMPOSITION REQUIRED" in c
            for c in (issue.comments or [])
        )
        if not has_spec:
            return ""
        from spec_match import build_spec_context  # noqa: PLC0415

        spec = build_spec_context(issue)
        # Truncate to avoid prompt bloat
        if len(spec) > 3000:
            spec = spec[:3000] + "\n... [truncated]"
        return (
            "\nSpec-match check (CRITICAL for product-track issues):\n"
            "- Compare your implementation against the original product direction below\n"
            "- Every requirement in the spec must be addressed in the code\n"
            "- If anything is missing, implement it now before proceeding\n"
            f"\n<details><summary>Original Spec</summary>\n\n{spec}\n\n</details>\n"
        )

    @staticmethod
    def _build_requirements_gap_section(issue: Task) -> str:
        """Build requirements gap detection section if issue has spec context."""
        has_spec = any(
            "Selected Product Direction" in c or "DECOMPOSITION REQUIRED" in c
            for c in (issue.comments or [])
        )
        if not has_spec:
            return ""
        from spec_match import build_requirements_gap_prompt  # noqa: PLC0415

        return build_requirements_gap_prompt(issue)

    def _build_tdd_subagent_prompt(
        self,
        plan_comment: str,
        bead_mapping: dict[str, str] | None = None,
    ) -> str:
        """Build a Task Graph plan that instructs the agent to use sub-agents.

        Parses phases from the plan, topologically sorts them, and builds
        concrete per-phase RED/GREEN/REFACTOR sub-agent instructions with
        the actual files, tests, and dependency info from each phase.

        When *bead_mapping* is provided, identifies each phase's factory-owned
        JSONL task. HydraFlow owns its lifecycle around the verified agent run;
        agents must not invoke the host ``bd`` CLI or edit the store directly.
        """
        phases = topological_sort(extract_phases(plan_comment))
        max_fix = self._config.tdd_max_remediation_loops

        header = (
            "\n\n## Implementation Plan — TDD Sub-Agent Isolation\n\n"
            "This plan uses a **Task Graph**. For each phase below, launch "
            "**three sub-agents** using the **Agent tool** in strict sequence.\n\n"
        )

        rules = (
            "### Rules\n\n"
            "- Complete each phase fully (RED \u2192 GREEN \u2192 REFACTOR) before "
            "starting the next\n"
            "- Each sub-agent runs in the same worktree and sees prior commits\n"
            "- If a sub-agent fails, report the failure with details \u2014 do NOT "
            "retry silently\n"
            f"- REFACTOR sub-agent may attempt up to **{max_fix}** fix cycles "
            "before reporting failure\n\n"
            "**Example:** If a phase shows `Bead: #task-123`, launch its "
            "RED, GREEN, and REFACTOR sub-agents as specified. Do not claim or "
            "close that task; HydraFlow updates its JSONL lifecycle after the "
            "verified run.\n\n"
        )

        phase_sections: list[str] = []
        for i, phase in enumerate(phases, 1):
            files_str = ", ".join(f"`{f}`" for f in phase.files) or "(none listed)"
            tests_str = (
                "\n".join(f"  - {t}" for t in phase.tests) or "  - (none listed)"
            )
            deps_str = ", ".join(phase.depends_on) or "none"

            # The mapping is informational inside an agent session. HydraFlow
            # owns lifecycle transitions; the database-backed host bd CLI must
            # never be pointed at this worktree-local JSONL store.
            bead_id = (bead_mapping or {}).get(phase.id)
            bead_header = ""
            if bead_id:
                bead_header = (
                    f"**Bead:** #{bead_id}  \n"
                    "> Factory-owned JSONL record; do not run `bd` in this "
                    "worktree or edit it directly. HydraFlow owns lifecycle.\n"
                )

            phase_sections.append(
                f"### Phase {i}: {phase.name}\n\n"
                f"{bead_header}"
                f"**Files:** {files_str}  \n"
                f"**Depends on:** {deps_str}\n\n"
                f"**1. RED sub-agent** \u2014 Launch with prompt:\n"
                f'> "Write FAILING tests for {phase.name}. '
                f"Test these behavioral specs:\n{tests_str}\n"
                f"ONLY create/modify files in `tests/`. Do NOT touch source files. "
                f'Commit when done."\n\n'
                f"**2. GREEN sub-agent** \u2014 Launch with prompt:\n"
                f'> "Implement the MINIMUM code to make all failing tests pass '
                f"for {phase.name}. Modify these files: {files_str}. "
                f"ONLY change source/implementation files (NOT test files). "
                f'Commit when done."\n\n'
                f"**3. REFACTOR sub-agent** \u2014 Launch with prompt:\n"
                f'> "Run `make test`. If tests fail, fix implementation code '
                f"(not tests). Repeat until the full suite passes (max "
                f'{max_fix} attempts). Commit fixes."\n\n'
            )

        # If parsing found no phases, include the raw plan as fallback
        if not phase_sections:
            return (
                "\n\n## Implementation Plan\n\n"
                "Follow this plan closely. It uses a **Task Graph** with "
                "ordered phases.\n"
                "Execute phases in order (P1 before P2, etc.). For each phase:\n"
                "1. Write tests that encode the behavioral specs listed.\n"
                "2. Run tests \u2014 they should FAIL.\n"
                "3. Implement the minimum code to make tests pass.\n"
                "4. Run the full test suite before moving to the next phase.\n\n"
                f"{plan_comment}"
            )

        return header + rules + "\n".join(phase_sections)

    async def _build_prompt_with_stats(
        self,
        issue: Task,
        review_feedback: str = "",
        prior_failure: str = "",
        bead_mapping: dict[str, str] | None = None,
        human_guidance: str = "",
        attempt_number: int = 0,
    ) -> tuple[str, dict[str, object]]:
        """Build the implementation prompt and pruning stats."""
        builder = PromptBuilder()
        plan_comment, other_comments = self._extract_plan_comment(issue.comments)
        raw_plan = plan_comment

        # Fallback to saved plan file
        if not plan_comment:
            plan_comment = self._load_plan_fallback(issue.id)
            raw_plan = plan_comment
            if not plan_comment:
                logger.error(
                    "No plan found for issue #%d — implementer will proceed without a plan",
                    issue.id,
                    extra={"issue": issue.id},
                )

        plan_section = ""
        if plan_comment:
            plan_comment = self._summarize_for_prompt(
                plan_comment,
                max_chars=self._config.max_impl_plan_chars,
                label="Implementation plan",
            )
            builder.record_history("Implementation plan", raw_plan, plan_comment)
            # Detect whether the plan uses Task Graph format
            if has_task_graph(plan_comment):
                plan_section = self._build_tdd_subagent_prompt(
                    plan_comment, bead_mapping=bead_mapping
                )
            else:
                plan_section = (
                    f"\n\n## Implementation Plan\n\n"
                    f"Follow this plan closely. It was created by a planner agent "
                    f"that already analyzed the codebase.\n\n"
                    f"{plan_comment}"
                )

        review_feedback_section = ""
        if review_feedback:
            raw_review_feedback = review_feedback
            review_feedback = self._summarize_for_prompt(
                review_feedback,
                max_chars=self._config.max_review_feedback_chars,
                label="Review feedback",
            )
            builder.record_history(
                "Review feedback", raw_review_feedback, review_feedback
            )
            review_feedback_section = (
                f"\n\n## Review Feedback\n\n"
                f"A reviewer rejected the previous implementation. "
                f"Address all feedback below:\n\n"
                f"{review_feedback}"
            )

        prior_failure_section = ""
        if prior_failure:
            raw_prior_failure = prior_failure
            prior_failure = self._summarize_for_prompt(
                prior_failure,
                max_chars=self._config.error_output_max_chars,
                label="Prior failure",
            )
            builder.record_history("Prior failure", raw_prior_failure, prior_failure)
            # Diverse-retry: the attempt budget is 3 near-identical tries
            # against the same wall unless the retry is told to pivot. The
            # directive rides the prior-failure section only — review-feedback
            # retries (which suppress prior_failure) keep their own framing.
            attempt_line = (
                f"This is attempt {attempt_number} of "
                f"{self._config.max_issue_attempts}; the budget exhausts "
                f"after that and a human is paged. "
                if attempt_number >= 1
                else ""
            )
            prior_failure_section = (
                f"\n\n## Prior Attempt Failure\n\n"
                f"Your previous implementation attempt failed with the following error. "
                f"Avoid repeating the same mistake:\n\n"
                f"```\n{prior_failure}\n```\n\n"
                f"{attempt_line}"
                f"Do NOT retry the same approach: first diagnose why the "
                f"previous attempt failed, then take a materially different "
                f"strategy — a different design, different files, or a "
                f"different diagnosis of the root cause."
            )

        comments_section = ""
        if other_comments:
            max_comments = 6
            selected_comments = other_comments[:max_comments]
            compact_comments = [
                self._truncate_comment_for_prompt(c) for c in selected_comments
            ]
            formatted = "\n".join(f"- {c}" for c in compact_comments)
            builder.record_history("Discussion", "".join(other_comments), formatted)
            comments_section = (
                f"\n\n## Discussion\n{fence_untrusted('issue_comments', formatted)}"
            )
            if len(other_comments) > max_comments:
                comments_section += f"\n- ... ({len(other_comments) - max_comments} more comments omitted)"

        guidance_section = fenced_steering_guidance(human_guidance)

        raw_feedback_section = self._get_review_feedback_section()
        feedback_section = ""
        if raw_feedback_section:
            compact_feedback = self._summarize_for_prompt(
                raw_feedback_section,
                max_chars=self._config.max_common_feedback_chars,
                label="Common review feedback",
            )
            builder.record_history(
                "Common review feedback", raw_feedback_section, compact_feedback
            )
            feedback_section = compact_feedback

        escalations = self._get_escalation_data()
        escalation_section = ""
        if escalations:
            blocks = [str(e["mandatory_block"]) for e in escalations]
            escalation_section = "\n\n" + "\n\n".join(blocks)
            builder.record_history(
                "Escalations", escalation_section, escalation_section
            )

        memory_section = await self._inject_memory(
            query_context=f"{issue.title}\n{(issue.body or '')[:200]}",
        )

        # Runtime log injection
        log_section = ""
        from log_context import load_runtime_logs  # noqa: PLC0415

        logs = load_runtime_logs(self._config)
        if logs:
            log_section = f"\n\n## Recent Application Logs\n\n```\n{logs}\n```"

        # Truncate issue body if too long
        body = issue.body
        max_body = self._config.max_issue_body_chars
        if len(body) > max_body:
            body = (
                body[:max_body]
                + f"\n\n[Body truncated at {max_body:,} chars — see full issue on GitHub]"
            )
        builder.record_context("Issue body", issue.body, body)

        # --- Cross-section paragraph dedup ---
        from prompt_dedup import PromptDeduplicator  # noqa: PLC0415

        section_deduper = PromptDeduplicator()
        deduped, section_chars_saved = section_deduper.dedup_sections(
            ("Issue body", body),
            ("Implementation plan", plan_section),
            ("Review feedback", review_feedback_section),
            ("Prior failure", prior_failure_section),
            ("Discussion", comments_section),
            ("Memory", memory_section),
            ("Human steering", guidance_section),
        )
        dedup_map = dict(deduped)
        body = dedup_map["Issue body"]
        plan_section = dedup_map["Implementation plan"]
        review_feedback_section = dedup_map["Review feedback"]
        prior_failure_section = dedup_map["Prior failure"]
        comments_section = dedup_map["Discussion"]
        memory_section = dedup_map["Memory"]
        guidance_section = dedup_map["Human steering"]

        if section_chars_saved:
            self._last_context_stats["section_dedup_chars_saved"] = section_chars_saved

        test_cmd = self._config.test_command  # noqa: F841 — used in f-string prompt
        tools_section = format_tools_for_prompt(discover_tools(self._config.repo_root))
        skills_section = format_skills_for_prompt(get_skills())
        plugin_skills_section = format_plugin_skills_for_prompt(
            skills_for_phase(
                "agent",
                discover_plugin_skills(self._config.required_plugins),
                self._config.phase_skills,
            )
        )

        prompt = f"""You are implementing GitHub issue #{issue.id}.

{UNTRUSTED_DATA_PREAMBLE}
## Issue #{issue.id}

### Title
{fence_untrusted("issue_title", issue.title)}

### Description
{fence_untrusted("issue_body", body)}{plan_section}{review_feedback_section}{prior_failure_section}{comments_section}{guidance_section}{memory_section}{log_section}

## Instructions

Work strictly test-first (RED → GREEN → REFACTOR): one failing test at a time,
minimal code to make it pass, full suite every cycle, no code a test doesn't require.
Run the available tools at their checkpoints (see below) and fix findings, then
commit with: "Fixes #{issue.id}: <concise summary>"

{tools_section}

{skills_section}
{feedback_section}{escalation_section}
{self._build_self_check_checklist(escalations)}
{self._build_requirements_gap_section(issue)}
## UI Guidelines

- Before creating UI components, search `src/ui/src/components/` for existing patterns to reuse.
- Import constants, types, and shared styles from centralized modules (e.g. `src/ui/src/constants.js`, `src/ui/src/theme.js`) — never duplicate.
- Apply responsive design: set `minWidth` on layout containers, use `flexShrink: 0` on fixed-width panels.
- Match existing spacing (4px grid), colors (CSS variables from `theme.js`), and component conventions.

## Rules

- Follow the project's CLAUDE.md guidelines strictly. NEVER delete or overwrite
  existing CLAUDE.md content — append or extend only; preserve everything present.
- Tests are mandatory. Run tests with: `{test_cmd}`
- Do NOT push to remote or create pull requests — never run `git push` or `gh pr create`.
- Run `make quality-lite` (lint + typecheck + security, no tests) as a sense check.
  CI runs the full test suite — you do not need to run `make quality` or `make test`.
- ALWAYS commit your work (`git add <file>` + `git commit`) — the system runs its own
  quality gate after you finish; your job is to produce commits.
- NEVER use interactive git commands (`git add -i`, `git add -p`, `git rebase -i`) —
  there is no TTY and they hang.
- NEVER conclude that the issue is "already satisfied" or that no work is needed —
  the planner already verified it requires implementation. Always produce commits.
- Do NOT bundle unrelated refactoring (renames, reformatting, factory migrations in
  files you are not otherwise changing). Each concern is a separate PR.

{MEMORY_SUGGESTION_PROMPT.format(context="implementation")}"""
        if plugin_skills_section:
            prompt = f"{prompt}\n\n{plugin_skills_section}"
        return prompt, builder.build_stats()
