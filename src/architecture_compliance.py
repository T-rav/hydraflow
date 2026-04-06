"""Architecture Compliance skill — checks branch diff for layer boundary violations.

Portable across Claude, Codex, and Pi backends. The skill is a pure prompt
executed by whichever agent CLI is configured; structured markers in the
transcript are parsed to determine pass/fail.
"""

from __future__ import annotations

import re


def build_architecture_compliance_prompt(
    *, issue_number: int, issue_title: str, diff: str, **_kwargs: object
) -> str:
    """Build a prompt that asks an agent to check a diff for architecture violations."""
    return f"""You are running the Architecture Compliance skill for issue #{issue_number}: {issue_title}.

Review the git diff below and check for architectural violations in the changed code.

## Diff

```diff
{diff}
```

## Architecture Layer Model

The codebase follows a 4-layer architecture. Higher layers may import from lower
layers but NEVER the reverse:

- **L1 (Foundation)**: config, models, events, state, subprocess utilities
- **L2 (Infrastructure)**: git/worktree management, PR manager, issue fetcher/store
- **L3 (Runners)**: agent, planner, reviewer, HITL runner, base runner
- **L4 (Orchestration)**: phases, orchestrator, background loops, service registry

Cross-cutting modules (events, state, ports) can be imported BY any layer but
must only import FROM L1.

`service_registry.py` is the composition root and is exempt from layer checks.

## Checks

1. **Upward imports** — L1 must not import from L2/L3/L4; L2 must not import from L3/L4; L3 must not import from L4
2. **Circular imports** — new import cycles introduced by the change
3. **Phase coupling** — phases/runners importing directly from other phases/runners (should go through ports)

## Instructions

- Only flag CLEAR violations visible in the diff. Do not flag pre-existing issues.
- Be conservative — only flag imports that clearly violate the layer model.
- Do NOT modify any files. This is a read-only review.

## Required Output

If no violations found:
ARCHITECTURE_COMPLIANCE_RESULT: OK
SUMMARY: No architecture violations found

If violations found:
ARCHITECTURE_COMPLIANCE_RESULT: RETRY
SUMMARY: <comma-separated list of violation categories>
VIOLATIONS:
- <file:line — description of violation>
"""


def parse_architecture_compliance_result(
    transcript: str,
) -> tuple[bool, str, list[str]]:
    """Parse the structured output from an architecture compliance transcript.

    Returns ``(passed, summary, violations)``.
    """
    status_match = re.search(
        r"ARCHITECTURE_COMPLIANCE_RESULT:\s*(OK|RETRY)", transcript, re.IGNORECASE
    )
    if not status_match:
        return True, "No explicit result marker", []

    passed = status_match.group(1).upper() == "OK"
    summary_match = re.search(r"SUMMARY:\s*(.+)", transcript, re.IGNORECASE)
    summary = summary_match.group(1).strip() if summary_match else ""

    violations: list[str] = []
    violations_match = re.search(
        r"VIOLATIONS:\s*\n((?:\s*-\s*.+\n?)+)", transcript, re.IGNORECASE
    )
    if violations_match:
        for line in violations_match.group(1).splitlines():
            stripped = line.strip().lstrip("- ").strip()
            if stripped:
                violations.append(stripped)

    return passed, summary, violations
