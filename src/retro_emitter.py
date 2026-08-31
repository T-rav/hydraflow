"""Route validated retrospective findings to the right destination.

GATE and BUGFIX are pattern-shaped by construction — the signal behind them
spans N issues — so they file ONE class issue via ``file_or_fold`` and later
siblings fold into it rather than spawning a sibling issue per site (#11292).

POLICY takes the memory-suggestion path instead. A rule that changes how the
factory behaves is signed by a human, not merged by a bot; that is the
harnessed-not-autonomous property the wiki records.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from exception_classify import reraise_on_credit_or_bug
from find_class_key import file_or_fold
from phase_utils import file_memory_suggestion
from retro_findings import BugfixFinding, GateFinding, PolicyFinding

if TYPE_CHECKING:
    from collections.abc import Sequence

    from config import HydraFlowConfig
    from ports import PRPort
    from retro_findings import RetroFinding
    from retro_signals import RetroSignal

logger = logging.getLogger("hydraflow.retro_emitter")

FIND_LABEL = "hydraflow-find"


async def emit(
    findings: Sequence[RetroFinding],
    signals: Sequence[RetroSignal],
    prs: PRPort | None,
    config: HydraFlowConfig,
) -> dict[str, int]:
    """File validated findings, capped per tick. Returns per-outcome counts."""
    counts = {"filed": 0, "policy": 0, "errors": 0, "capped": 0}
    if prs is None:
        logger.debug("Retro emission skipped: no PR port wired")
        return counts

    by_id = {s.id: s for s in signals}
    cap = config.retro_findings_max_per_tick

    ordered = list(findings)
    counts["capped"] = max(0, len(ordered) - cap)
    for finding in ordered[:cap]:
        signal = by_id.get(finding.signal_id)
        if signal is None:
            continue
        try:
            await _emit_one(finding, signal, prs, config, counts)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "Retro emission failed for %r — continuing",
                finding.title,
                exc_info=True,
            )
            counts["errors"] += 1

    return counts


async def _emit_one(
    finding: RetroFinding,
    signal: RetroSignal,
    prs: PRPort,
    config: HydraFlowConfig,
    counts: dict[str, int],
) -> None:
    if isinstance(finding, PolicyFinding):
        await _file_policy(finding, signal, config)
        counts["policy"] += 1
        return

    number = await file_or_fold(
        prs,
        source="retrospective",
        needle=signal.signature,
        title=finding.title,
        body=_body(finding, signal),
        labels=[FIND_LABEL],
        site=_site(finding),
    )
    # create_issue returns 0 on failure — the existing 0-sentinel contract.
    if number:
        counts["filed"] += 1


def _site(finding: RetroFinding) -> str:
    if isinstance(finding, GateFinding):
        return finding.guard_path
    if isinstance(finding, BugfixFinding):
        return finding.repro_file
    return finding.doc_path


def _body(finding: RetroFinding, signal: RetroSignal) -> str:
    lines = [
        f"**Observed {signal.count}×** across issues "
        f"{', '.join(f'#{n}' for n in signal.issues)}.",
        "",
        f"**Signal** (`{signal.family}`): `{signal.signature}`",
        "",
    ]
    if finding.rationale:
        lines += [finding.rationale, ""]

    if isinstance(finding, GateFinding):
        lines += [
            f"**Proposed guard:** `{finding.guard_path}`",
            f"**Observation:** {finding.observed}",
        ]
    elif isinstance(finding, BugfixFinding):
        lines += [
            f"**Repro:** `{finding.repro_command}`",
            f"**File:** `{finding.repro_file}`",
            "",
            "```",
            finding.error_excerpt,
            "```",
        ]

    if signal.evidence:
        lines += ["", "<details><summary>Evidence</summary>", ""]
        for ref in signal.evidence:
            lines += [f"`{ref.locator}`", "", "```", ref.excerpt, "```", ""]
        lines.append("</details>")

    lines += ["", "---", "*Auto-detected by the HydraFlow retrospective.*"]
    return "\n".join(lines)


async def _file_policy(
    finding: PolicyFinding, signal: RetroSignal, config: HydraFlowConfig
) -> None:
    pseudo_transcript = (
        "MEMORY_SUGGESTION_START\n"
        f"principle: {finding.rule_text}\n"
        f"rationale: Observed {signal.count}x across issues {signal.issues} — "
        f"{signal.signature}. Target doc: {finding.doc_path}.\n"
        "failure_mode: Recurring pipeline failure detected by retrospective\n"
        "scope: hydraflow\n"
        "MEMORY_SUGGESTION_END"
    )
    await file_memory_suggestion(
        pseudo_transcript, "retrospective", finding.title, config
    )


__all__ = ["FIND_LABEL", "emit"]
