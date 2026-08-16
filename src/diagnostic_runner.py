"""Diagnostic runner — two-stage agent for self-healing."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from agent_cli import build_agent_command
from base_runner import BaseRunner
from exception_classify import reraise_on_credit_or_bug
from subprocess_util import (
    CreditExhaustedError,
    is_credit_exhaustion,
    parse_credit_resume_time,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from models import EscalationContext

from models import DiagnosisResult, Severity

logger = logging.getLogger("hydraflow.diagnostic")


def _extract_json(text: str) -> dict[str, object] | None:
    """Extract first JSON block from agent output."""
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    raw = match.group(1).strip() if match else text.strip()
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def _build_diagnosis_prompt(
    issue_number: int,
    issue_title: str,
    issue_body: str,
    context: EscalationContext,
) -> str:
    """Build the Stage 1 diagnosis prompt with full context."""
    sections = [
        f"# Diagnostic Analysis — Issue #{issue_number}\n",
        f"**Title:** {issue_title}\n",
        f"**Body:**\n{issue_body or '_No description provided._'}\n",
        f"**Escalation cause:** {context.cause}\n",
        f"**Origin phase:** {context.origin_phase}\n",
    ]
    if context.ci_logs:
        # Tail, not head: the failure evidence lives at the end of a CI log,
        # and an unbounded log (a full pytest run can be tens of MB) made the
        # prompt so large that gating/streaming it froze the event loop
        # (#9879) and burned tokens the model never needed.
        sections.append(f"**CI Logs (tail):**\n```\n{context.ci_logs[-8000:]}\n```\n")
    if context.review_comments:
        sections.append(
            "**Review Feedback:**\n"
            + "\n".join(f"- {c}" for c in context.review_comments)
            + "\n"
        )
    if context.pr_diff:
        sections.append(f"**PR Diff:**\n```diff\n{context.pr_diff[:12000]}\n```\n")
    if context.code_scanning_alerts:
        sections.append(
            "**Code Scanning Alerts:**\n"
            + "\n".join(f"- {a}" for a in context.code_scanning_alerts)
            + "\n"
        )
    if context.previous_attempts:
        lines = []
        for a in context.previous_attempts:
            lines.append(
                f"- Attempt {a.attempt_number}: "
                f"{'made changes' if a.changes_made else 'no changes'}, "
                f"error: {a.error_summary}"
            )
        sections.append("**Previous Attempts:**\n" + "\n".join(lines) + "\n")
    if context.agent_transcript:
        sections.append(
            f"**Agent Reasoning (failed attempt):**\n{context.agent_transcript[:4000]}\n"
        )
    sections.append(
        "\n## Instructions\n\n"
        "Analyze the root cause. Classify severity:\n"
        "- P0: Secrets exposure, auth bypass, data loss\n"
        "- P1: Pipeline blocked, crash loop, state corruption\n"
        "- P2: Wrong behavior, system keeps running\n"
        "- P3: Missing wiring, incomplete setup\n"
        "- P4: Housekeeping, renaming, non-urgent\n\n"
        "Respond with a JSON block:\n"
        "```json\n"
        '{"root_cause": "...", "severity": "P0-P4", "fixable": true/false, '
        '"fix_plan": "...", "human_guidance": "...", "affected_files": [...]}\n'
        "```"
    )
    return "\n".join(sections)


class DiagnosticRunner(BaseRunner):
    """Two-stage diagnostic agent: diagnose (read-only), then fix (in worktree)."""

    # #9895: diagnosis agents quote credit-error prose from the failed
    # issue's transcripts; scanning that prose raised a false global
    # CreditExhaustedError on essentially every run (the flood that got
    # this loop kill-switched). Structured/stderr credit signals still fire.
    CREDIT_PROSE_SCAN = False

    _log = logger

    def _build_command(self, _worktree_path: Path | None = None) -> list[str]:
        """Build the diagnostic agent command."""
        return build_agent_command(
            tool=self._config.implementation_tool,
            model=self._config.model,
        )

    def _mockworld_diagnosis(self) -> DiagnosisResult | None:
        """MockWorld bypass for the air-gapped sandbox (ADR-0063 pattern).

        When a ``_mockworld_fake_llm`` sentinel is attached (set by
        ``sandbox_main`` on the diagnostic runner), Stage-1 diagnosis must
        not spawn a real ``claude`` subprocess — the sandbox is
        ``internal: true`` and the call would hang on api-retry backoff,
        stranding the issue in ``hydraflow-diagnose`` until the scenario
        times out (s05). Return a not-fixable diagnosis so the loop
        escalates straight to HITL — the path s05 exercises. Returns
        ``None`` in production so the real subprocess path runs.
        """
        fake_llm = getattr(self, "_mockworld_fake_llm", None)
        if fake_llm is None or not getattr(fake_llm, "_is_fake_adapter", False):
            return None
        return DiagnosisResult(
            root_cause="MockWorld sandbox diagnosis (no real agent)",
            severity=Severity.P2_FUNCTIONAL,
            fixable=False,
            fix_plan="",
            human_guidance="Sandbox diagnostic bypass — escalating to human review.",
        )

    async def diagnose(
        self,
        issue_number: int,
        issue_title: str,
        issue_body: str,
        context: EscalationContext,
        *,
        issue_labels: Sequence[str] = (),
    ) -> DiagnosisResult:
        """Stage 1: Read-only diagnosis against repo root. Returns structured result.

        *issue_labels* is threaded from the diagnostic loop's issue listing
        so the CH-6 gate's upward-only ``data-class:`` label elevation
        applies to the diagnosis spawn (#10000).
        """
        bypass = self._mockworld_diagnosis()
        if bypass is not None:
            return bypass
        prompt = _build_diagnosis_prompt(issue_number, issue_title, issue_body, context)
        try:
            cmd = self._build_command()
            transcript = await self._execute(
                cmd,
                prompt,
                self._config.repo_root,
                {"issue": issue_number, "source": "diagnostic"},
                issue_labels=issue_labels,
            )
        except (PermissionError, KeyboardInterrupt, SystemExit, MemoryError):
            raise
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.exception("Diagnostic agent failed for issue #%d", issue_number)
            return DiagnosisResult(
                root_cause="Diagnostic agent crashed",
                severity=Severity.P2_FUNCTIONAL,
                fixable=False,
                fix_plan="",
                human_guidance="Diagnostic agent encountered an error. Manual review required.",
            )

        parsed = _extract_json(transcript)
        if parsed is None:
            # #10536: the diagnose agent hit a usage/credit limit and returned
            # no structured output. That is an INFRA failure, not a genuine
            # "not fixable" verdict — a fabricated ``fixable=False`` here gets
            # escalated to HITL (scattering every credit-starved issue into the
            # human queue) and, worse, never triggers the orchestrator's global
            # credit-pause. Raise ``CreditExhaustedError`` so it propagates
            # through ``reraise_on_credit_or_bug`` to ``_handle_credit_exhaustion``
            # and the whole factory pauses until the limit resets. The CLI only
            # raises the error on some paths; the no-JSON-with-credit-text path
            # is the one that leaked (weekly limit → soft failure).
            if transcript and is_credit_exhaustion(transcript):
                # ``parsed is None`` means the diagnose agent produced NO valid
                # JSON — the signature of the agent's own run being cut off by the
                # cap, not a completed analysis that merely quotes a prior cap. So
                # this is authoritative: the orchestrator must pause directly and
                # not route it through the weekly-blind probe that would discard it
                # (completes #10537's intent; see #10558).
                raise CreditExhaustedError(
                    "Diagnostic agent hit a usage/credit limit — no structured output",
                    resume_at=parse_credit_resume_time(transcript),
                    authoritative=True,
                )
            # #11370: on the failover lane the harness model's format
            # compliance is weaker — a parse failure there is an INFRA
            # signal about the lane, not evidence about the issue. Mark it
            # so the loop parks/retries instead of escalating to HITL
            # (observed live: false 'diagnose-failed' escalations while GLM
            # served the fleet).
            from credit_failover import is_active as _failover_active

            return DiagnosisResult(
                root_cause=transcript[:500] if transcript else "No output",
                severity=Severity.P2_FUNCTIONAL,
                fixable=False,
                fix_plan="",
                human_guidance="Agent did not produce structured output. Manual review required.",
                infra_failure=_failover_active(),
            )

        try:
            return DiagnosisResult.model_validate(parsed)
        except Exception:
            logger.warning(
                "DiagnosisResult validation failed for issue #%d — using fallback",
                issue_number,
                exc_info=True,
            )
            logger.debug(
                "raw parsed diagnosis dict for issue #%d: %s",
                issue_number,
                parsed,
            )
            return DiagnosisResult(
                root_cause=str(
                    parsed.get("root_cause", transcript[:500] if transcript else "")
                ),
                severity=Severity.P2_FUNCTIONAL,
                fixable=False,
                fix_plan=str(parsed.get("fix_plan", "")),
                human_guidance="Agent output did not validate. Manual review required.",
            )

    async def fix(
        self,
        issue_number: int,
        issue_title: str,
        issue_body: str,
        diagnosis: DiagnosisResult,
        wt_path: str,
        *,
        issue_labels: Sequence[str] = (),
    ) -> tuple[bool, str]:
        """Stage 2: Attempt fix in worktree. Returns (success, transcript).

        *issue_labels* is threaded from the diagnostic loop's issue listing
        so the CH-6 gate's upward-only ``data-class:`` label elevation
        applies to the fix spawn (#10000).
        """
        prompt = (
            f"# Fix Issue #{issue_number}: {issue_title}\n\n"
            f"**Root Cause:** {diagnosis.root_cause}\n\n"
            f"**Fix Plan:** {diagnosis.fix_plan}\n\n"
            f"**Affected Files:** {', '.join(diagnosis.affected_files)}\n\n"
            f"**Issue Body:**\n{issue_body}\n\n"
            "Apply the fix. Run `make quality` to verify. "
            "Commit your changes with a descriptive message."
        )
        wt = Path(wt_path)
        try:
            cmd = self._build_command(wt)
            transcript = await self._execute(
                cmd,
                prompt,
                wt,
                {"issue": issue_number, "source": "diagnostic_fix"},
                issue_labels=issue_labels,
            )
            verify = await self._verify_quality(wt)
            return verify.passed, transcript
        except (PermissionError, KeyboardInterrupt, SystemExit, MemoryError):
            raise
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.exception("Diagnostic fix failed for issue #%d", issue_number)
            return False, "Fix agent crashed"
