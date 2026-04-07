"""Architecture Compliance skill — diff-focused architectural boundary check.

Lightweight, per-PR complement to the full ``/hf.audit-architecture`` sweep.
Checks the branch diff for layer violations, coupling, domain pollution,
missing abstractions, and infrastructure bypass using LLM judgment.

Complements (does not duplicate) the static ``make layer-check`` (#6048).
"""

from __future__ import annotations

import re


def build_arch_compliance_prompt(
    *, issue_number: int, issue_title: str, diff: str, **_kwargs: object
) -> str:
    """Build a prompt that asks an agent to review a diff for architecture violations."""
    return f"""You are running the Architecture Compliance Check skill for issue #{issue_number}: {issue_title}.

Review the git diff below and check for architectural violations against the HydraFlow layer model.

## HydraFlow Layer Model

The codebase has four layers. Dependencies MUST flow inward only (higher layers depend on lower layers, never the reverse):

```
Layer 4 — Infrastructure/Adapters (I/O, external systems)
  pr_manager.py, worktree.py, merge_conflict_resolver.py,
  post_merge_handler.py, dashboard.py, dashboard_routes/

Layer 3 — Runners (subprocess orchestration, agent invocation)
  base_runner.py, agent.py, planner.py, reviewer.py,
  hitl_runner.py, triage_runner.py, runner_utils.py,
  skill_registry.py, diff_sanity.py, scope_check.py,
  test_adequacy.py, plan_compliance.py, arch_compliance.py

Layer 2 — Application (phase coordination, workflow orchestration)
  orchestrator.py, plan_phase.py, implement_phase.py, review_phase.py,
  triage_phase.py, hitl_phase.py, phase_utils.py, pr_unsticker.py,
  base_background_loop.py, *_loop.py (background loops)

Layer 1 — Domain (pure data, business rules, no I/O)
  models.py, config.py

Cross-cutting (available to all, imports only from Domain):
  events.py, state/

Composition root (imports from ALL layers — exempt from direction checks):
  service_registry.py
```

**Dependency direction rule:** A module at Layer N may import from layers 1..N but NEVER from layer N+1 or above. Cross-cutting modules may import from Layer 1 only. ``service_registry.py`` is the composition root and is exempt from direction checks.

## Violation Categories

Check for these five categories:

1. **Layer boundary violations** — New imports that go upward (Layer N importing Layer N+1). Example: a runner importing from ``pr_manager`` (Layer 3→4).
2. **New coupling** — Phase importing another phase, runner importing another runner, infrastructure module used directly in application layer.
3. **Domain pollution** — Infrastructure types (HTTP responses, subprocess results, file handles) leaking into ``models.py`` or ``config.py``.
4. **Missing abstraction** — New concrete dependency that should go through a protocol/port.
5. **Bypass detection** — Direct ``subprocess.run``, ``httpx.get``, ``open()`` in application/runner layers instead of through infrastructure adapters.

## Diff

```diff
{diff}
```

## Instructions

- Only flag clear violations that are unambiguously architectural problems.
- Do NOT flag ``service_registry.py`` for cross-layer imports — it is the composition root.
- Do NOT flag existing code that was not changed in this diff.
- Do NOT modify any files. This is a read-only review.
- Be conservative: when in doubt, pass. False positives block the pipeline.
- This skill complements the static ``make layer-check`` — focus on judgment-based issues that static tools cannot detect (coupling patterns, adapter thickness, interface design).

## Required Output

If all checks pass:
ARCH_COMPLIANCE_RESULT: OK
SUMMARY: No violations found

If violations are found:
ARCH_COMPLIANCE_RESULT: RETRY
SUMMARY: <comma-separated list of violation categories found>
VIOLATIONS:
- [SEVERITY] file:line - violation description - suggested fix
"""


def parse_arch_compliance_result(transcript: str) -> tuple[bool, str, list[str]]:
    """Parse the structured output from an architecture compliance check transcript.

    Returns ``(passed, summary, findings)``.
    """
    status_match = re.search(
        r"ARCH_COMPLIANCE_RESULT:\s*(OK|RETRY)", transcript, re.IGNORECASE
    )
    if not status_match:
        return True, "No explicit result marker", []

    passed = status_match.group(1).upper() == "OK"
    summary_match = re.search(r"SUMMARY:\s*(.+)", transcript, re.IGNORECASE)
    summary = summary_match.group(1).strip() if summary_match else ""

    findings: list[str] = []
    findings_match = re.search(
        r"VIOLATIONS:\s*\n((?:\s*-\s*.+\n?)+)", transcript, re.IGNORECASE
    )
    if findings_match:
        for line in findings_match.group(1).splitlines():
            stripped = line.strip().lstrip("- ").strip()
            if stripped:
                findings.append(stripped)

    return passed, summary, findings
