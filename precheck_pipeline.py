"""Shared precheck pipeline for low-tier subskill and debug escalation."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from agent_cli import build_agent_command
from config import HydraFlowConfig
from escalation_gate import high_risk_diff_touched, should_escalate_debug
from models import PrecheckResult


def parse_precheck_transcript(
    transcript: str,
) -> PrecheckResult:
    """Extract PRECHECK_* fields from a precheck transcript."""
    risk_match = re.search(
        r"PRECHECK_RISK:\s*(low|medium|high)",
        transcript,
        re.IGNORECASE,
    )
    confidence_match = re.search(
        r"PRECHECK_CONFIDENCE:\s*([0-9]*\.?[0-9]+)",
        transcript,
        re.IGNORECASE,
    )
    escalate_match = re.search(
        r"PRECHECK_ESCALATE:\s*(yes|no)",
        transcript,
        re.IGNORECASE,
    )
    summary_match = re.search(
        r"PRECHECK_SUMMARY:\s*(.*)",
        transcript,
        re.IGNORECASE,
    )
    parse_failed = not (
        risk_match and confidence_match and escalate_match and summary_match
    )
    risk = risk_match.group(1).lower() if risk_match else "medium"
    confidence = float(confidence_match.group(1)) if confidence_match else 0.0
    escalate = bool(escalate_match and escalate_match.group(1).lower() == "yes")
    summary = summary_match.group(1).strip() if summary_match else ""
    return PrecheckResult(
        risk=risk,
        confidence=confidence,
        escalate=escalate,
        summary=summary,
        parse_failed=parse_failed,
    )


def build_subskill_command(config: HydraFlowConfig) -> list[str]:
    """Build the CLI command for a subskill precheck invocation."""
    return build_agent_command(
        tool=config.subskill_tool,
        model=config.subskill_model,
    )


def build_debug_command(config: HydraFlowConfig) -> list[str]:
    """Build the CLI command for a debug escalation invocation."""
    return build_agent_command(
        tool=config.debug_tool,
        model=config.debug_model,
    )


async def run_precheck_pipeline(
    config: HydraFlowConfig,
    prompt: str,
    diff: str,
    execute: Callable[[list[str], str], Awaitable[str]],
    debug_suffix: str,
    execute_debug: Callable[[list[str], str], Awaitable[str]] | None = None,
) -> str:
    """Run the shared precheck pipeline: subskill retry loop + optional debug escalation.

    Parameters
    ----------
    config:
        HydraFlow configuration.
    prompt:
        The precheck prompt to send to the subskill agent.
    diff:
        The diff text, used for high-risk file detection.
    execute:
        Async callback ``(cmd, prompt) -> transcript`` that runs a subprocess.
    debug_suffix:
        Text appended to *prompt* when running the debug escalation call.
    execute_debug:
        Optional separate callback for the debug escalation call.  When
        omitted, *execute* is reused.  Pass a distinct callback when the
        caller wants a different event source or routing for debug runs.

    Returns
    -------
    str
        Joined context lines suitable for injection into a parent prompt.
    """
    if config.max_subskill_attempts <= 0:
        return "Low-tier precheck disabled."

    risk = "medium"
    confidence = config.subskill_confidence_threshold
    summary = ""
    parse_failed = False

    try:
        for _attempt in range(config.max_subskill_attempts):
            transcript = await execute(build_subskill_command(config), prompt)
            precheck = parse_precheck_transcript(transcript)
            risk = precheck.risk
            confidence = precheck.confidence
            summary = precheck.summary
            parse_failed = precheck.parse_failed
            if not parse_failed:
                break
    except Exception:  # noqa: BLE001
        return "Low-tier precheck failed; continuing without precheck context."

    decision = should_escalate_debug(
        enabled=config.debug_escalation_enabled,
        confidence=confidence,
        confidence_threshold=config.subskill_confidence_threshold,
        parse_failed=parse_failed,
        retry_count=config.max_subskill_attempts,
        max_subskill_attempts=config.max_subskill_attempts,
        risk=risk,
        high_risk_files_touched=high_risk_diff_touched(diff),
    )

    context = [
        f"Precheck risk: {risk}",
        f"Precheck confidence: {confidence:.2f}",
        f"Precheck summary: {summary or 'N/A'}",
        f"Debug escalation: {'yes' if decision.escalate else 'no'}",
    ]

    if decision.escalate and config.max_debug_attempts > 0:
        _execute_debug = execute_debug or execute
        debug_transcript = await _execute_debug(
            build_debug_command(config),
            prompt + debug_suffix,
        )
        context.append("Debug precheck transcript:")
        context.append(debug_transcript[:1000])
        context.append(f"Escalation reasons: {', '.join(decision.reasons)}")

    return "\n".join(context)
