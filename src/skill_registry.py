"""Declarative skill and tool registries for agent workflows.

Two registries:

1. **AgentSkill** — post-implementation checks run as separate subprocesses
   after the agent finishes (diff-sanity, test-adequacy). Orchestrated by
   ``AgentRunner._run_skill()``.

2. **AgentTool** — slash commands the agent should actively invoke during
   its work at specific workflow checkpoints. Injected into the agent's
   prompt so it knows what commands are available, when to run them, and why.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from diff_sanity import build_diff_sanity_prompt, parse_diff_sanity_result
from discover_completeness import (
    build_discover_completeness_prompt,
    parse_discover_completeness_result,
)
from plan_compliance import build_plan_compliance_prompt, parse_plan_compliance_result
from scope_check import build_scope_check_prompt, parse_scope_check_result
from shape_coherence import (
    build_shape_coherence_prompt,
    parse_shape_coherence_result,
)
from test_adequacy import (
    build_test_adequacy_prompt,
    build_test_adequacy_repair_prompt,
    build_test_adequacy_verifier_prompt,
    finder_asserted_adequate,
    parse_test_adequacy_result,
    parse_test_adequacy_verifier_result,
)


@dataclass(frozen=True)
class VerifierSpec:
    """An independent second-opinion pass attached to a skill (#9546).

    The verifier runs AFTER the skill's finder loop passes, and ONLY when
    ``trigger(finder_transcript)`` is true — for test-adequacy that means an
    explicit ``TEST_ADEQUACY_RESULT: OK`` marker, never the no-marker
    default-pass. The config keys are resolved with ``getattr(config, key)``
    at dispatch time so the knobs stay live-editable; a registry test guards
    each key against typo drift.

    Attributes
    ----------
    prompt_builder:
        ``(issue_number, issue_title, diff, **kwargs) -> str`` — builds the
        verifier prompt. Must not disclose the finder's verdict.
    result_parser:
        ``(transcript) -> (confirmed, summary, gaps)`` — ``confirmed=False``
        overrides the finder's pass.
    trigger:
        ``(finder_transcript) -> bool`` — explicit-OK gate.
    tool_config_key / model_config_key:
        ``HydraFlowConfig`` field names for the verifier CLI backend/model.
        The model must stay independent of the finder's ``review_model``.
    enabled_config_key:
        Kill-switch field name (default-on).
    fail_closed_config_key:
        Field name for the degraded-run policy (default fail-soft).
    """

    prompt_builder: Callable[..., str]
    result_parser: Callable[[str], tuple[bool, str, list[str]]]
    trigger: Callable[[str], bool]
    tool_config_key: str
    model_config_key: str
    enabled_config_key: str
    fail_closed_config_key: str


@dataclass(frozen=True)
class AgentSkill:
    """A post-implementation check that runs against the branch diff.

    Attributes
    ----------
    name:
        Short identifier (e.g. ``"diff-sanity"``).
    purpose:
        One-line description injected into the agent prompt so it knows
        what checks will run after it finishes.
    config_key:
        Name of the ``HydraFlowConfig`` field that controls max attempts.
        Set to 0 to disable the skill.
    blocking:
        If ``True``, a failed skill stops the pipeline. If ``False``,
        failures are logged as warnings.
    prompt_builder:
        ``(issue_number, issue_title, diff, **kwargs) -> str`` — builds the skill prompt.
        Skills that need the plan text receive it via the ``plan_text`` kwarg.
    result_parser:
        ``(transcript) -> (passed, summary, findings)`` — parses structured
        markers from the agent's response.
    verifier:
        Optional :class:`VerifierSpec` for an independent second-opinion pass
        (#9546). ``None`` for every skill except test-adequacy.
    repair_config_key:
        Name of the ``HydraFlowConfig`` field bounding in-run repair passes
        (#11593). When set (and the field > 0), a failing verdict dispatches
        the concrete findings back to the implementer worktree via
        ``repair_prompt_builder`` and re-runs the FULL check (coverage delta
        + verifier included) before the run is rejected. ``None`` disables
        repair for the skill. Only test-adequacy sets it today.
    repair_prompt_builder:
        ``(issue_number, issue_title, verdict_source, summary, findings,
        pass_number, max_passes, **kwargs) -> str`` — builds the focused
        "write exactly these missing tests" repair prompt. Required when
        ``repair_config_key`` is set.
    pin_config_key:
        Name of the ``HydraFlowConfig`` boolean that arms the demand contract
        (#11644). When set (and the field is true), a retry carrying the
        previous attempt's findings is judged against **that** demand rather
        than a freshly-derived one — see ``adequacy_demand.evaluate_demand``.
        ``None`` means the skill never receives a pinned demand. Only
        test-adequacy sets it today.
    """

    name: str
    purpose: str
    config_key: str
    blocking: bool
    prompt_builder: Callable[..., str]
    result_parser: Callable[[str], tuple[bool, str, list[str]]]
    coverage_check: bool = False
    verifier: VerifierSpec | None = None
    repair_config_key: str | None = None
    repair_prompt_builder: Callable[..., str] | None = None
    pin_config_key: str | None = None


# Built-in skills — registered in execution order
BUILTIN_SKILLS: list[AgentSkill] = [
    AgentSkill(
        name="diff-sanity",
        purpose="Review diff for accidental deletions, debug code, missing imports, scope creep, hardcoded secrets, and logic errors",
        config_key="max_diff_sanity_attempts",
        blocking=True,
        prompt_builder=build_diff_sanity_prompt,
        result_parser=parse_diff_sanity_result,
    ),
    AgentSkill(
        name="scope-check",
        purpose="Verify the diff only modifies files listed in the implementation plan",
        config_key="max_scope_check_attempts",
        blocking=True,
        prompt_builder=build_scope_check_prompt,
        result_parser=parse_scope_check_result,
    ),
    AgentSkill(
        name="plan-compliance",
        purpose="Verify implementation matches the planner's file deltas, task graph, and behavioral test specs",
        config_key="max_plan_compliance_attempts",
        blocking=False,
        prompt_builder=build_plan_compliance_prompt,
        result_parser=parse_plan_compliance_result,
    ),
    AgentSkill(
        name="test-adequacy",
        purpose="Assess whether changed production code has adequate test coverage, edge cases, and regression safety",
        config_key="max_test_adequacy_attempts",
        # Blocking (#9227): the deterministic coverage-delta check + LLM verdict
        # already run here pre-review, but as advisory warnings the implementer
        # never had to act on — so `missing_tests` kept recurring as a review
        # finding. Gating it (like diff-sanity/scope-check) shifts the catch
        # left: an uncovered changed line RETRIES the implementer via the
        # existing prior_failure seam before review ever classifies it. Disable
        # via max_test_adequacy_attempts=0 if it ever over-gates.
        blocking=True,
        prompt_builder=build_test_adequacy_prompt,
        result_parser=parse_test_adequacy_result,
        coverage_check=True,
        verifier=VerifierSpec(
            prompt_builder=build_test_adequacy_verifier_prompt,
            result_parser=parse_test_adequacy_verifier_result,
            trigger=finder_asserted_adequate,
            tool_config_key="test_adequacy_verifier_tool",
            model_config_key="test_adequacy_verifier_model",
            enabled_config_key="test_adequacy_verifier_enabled",
            fail_closed_config_key="test_adequacy_verifier_fail_closed",
        ),
        # Repair-in-run (#11593 seam 1): a failing verdict hands the concrete
        # findings back to the implementer for a bounded fix pass before the
        # run is rejected — 61 of 105 failed August runs died here, and the
        # cheapest fix ("write the three missing tests") was unreachable
        # without a full restart. Bounded by test_adequacy_repair_passes;
        # max_test_adequacy_attempts=0 still disables the gate entirely.
        repair_config_key="test_adequacy_repair_passes",
        repair_prompt_builder=build_test_adequacy_repair_prompt,
        # Demand contract (#11644 seam 2 follow-up): the calibration measured
        # 9 of 15 consecutive re-rejections demanding something ENTIRELY NEW
        # (mean overlap 0.04) and 75 % of findings naming nothing locatable, so
        # an implementer could satisfy the stated bar and be rejected anyway.
        # With this armed, a retry is judged against the demand the previous
        # attempt actually stated. Bounded by test_adequacy_pin_demand.
        pin_config_key="test_adequacy_pin_demand",
    ),
    AgentSkill(
        name="discover-completeness",
        purpose="Evaluate a Discover brief against the five-criterion rubric (structure, non-trivial content, no paraphrase-only, concrete acceptance criteria, open questions when ambiguous)",
        config_key="max_discover_attempts",
        blocking=True,
        prompt_builder=build_discover_completeness_prompt,
        result_parser=parse_discover_completeness_result,
    ),
    AgentSkill(
        name="shape-coherence",
        purpose="Evaluate a Shape proposal against the five-criterion rubric (≥2 options, do-nothing option, mutually exclusive scope, trade-offs named, reconciles Discover ambiguities)",
        config_key="max_shape_attempts",
        blocking=True,
        prompt_builder=build_shape_coherence_prompt,
        result_parser=parse_shape_coherence_result,
    ),
]


def get_skills() -> list[AgentSkill]:
    """Return all registered skills in execution order."""
    return list(BUILTIN_SKILLS)


def format_skills_for_prompt(skills: list[AgentSkill]) -> str:
    """Format skills as a prompt section so the agent knows what checks will run.

    Injected into the implementation agent's instructions so it understands
    the post-implementation quality gates.
    """
    if not skills:
        return ""
    lines = ["## Post-Implementation Skills", ""]
    lines.append("The following checks run automatically after your implementation:")
    lines.append("")
    for skill in skills:
        blocking_tag = "[blocking]" if skill.blocking else "[non-blocking]"
        lines.append(f"- **{skill.name}** {blocking_tag} — {skill.purpose}")
    lines.append("")
    lines.append(
        "If a blocking skill fails, you will be asked to fix the issues and the skill will re-run."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent Tools — slash commands discovered from .claude/commands/hf.*.md
# ---------------------------------------------------------------------------


_tool_logger = logging.getLogger("hydraflow.skill_registry")


@dataclass(frozen=True)
class AgentTool:
    """A slash command the agent should actively invoke during implementation.

    Discovered at runtime by scanning ``.claude/commands/hf.*.md`` files.
    """

    command: str
    purpose: str


def discover_tools(repo_root: str | Path) -> list[AgentTool]:
    """Scan ``.claude/commands/`` for ``hf.*.md`` files and build tool entries.

    Each file's stem becomes the command (e.g. ``hf.quality-gate.md`` →
    ``/hf.quality-gate``) and the first non-empty line starting with ``#``
    becomes the purpose.
    """
    commands_dir = Path(repo_root) / ".claude" / "commands"
    if not commands_dir.is_dir():
        return []

    tools: list[AgentTool] = []
    for path in sorted(commands_dir.glob("hf.*.md")):
        command = f"/{path.stem}"
        purpose = _extract_purpose(path)
        if purpose:
            tools.append(AgentTool(command=command, purpose=purpose))
        else:
            _tool_logger.debug("Skipping %s — no heading found", path.name)

    return tools


def _extract_purpose(path: Path) -> str:
    """Extract the first markdown heading from a command file as its purpose."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("#"):
                    return stripped.lstrip("#").strip()
        return ""
    except OSError:
        return ""


def format_tools_for_prompt(tools: list[AgentTool]) -> str:
    """Format discovered tools as a prompt section for the agent.

    The agent sees what commands are available and is instructed to run
    them at appropriate checkpoints during its work.
    """
    if not tools:
        return ""
    lines = ["## Available Tools", ""]
    lines.append(
        "Run each of these slash commands before committing; fix anything they report:"
    )
    lines.append("")
    for tool in tools:
        lines.append(f"- `{tool.command}` — {tool.purpose}")
    return "\n".join(lines)
