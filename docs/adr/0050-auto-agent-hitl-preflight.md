# ADR-0050: Auto-Agent HITL Pre-Flight Loop

- **Status:** Accepted
- **Date:** 2026-04-25
- **Supersedes:** none
- **Superseded by:** none
- **Related:** [ADR-0002](0002-labels-as-state-machine.md) (label state machine); [ADR-0029](0029-caretaker-loop-pattern.md) (caretaker loop pattern); [ADR-0044](0044-hydraflow-principles.md) (principles audit); [ADR-0045](0045-trust-architecture-hardening.md) (trust fleet + `hitl-escalation` label); [ADR-0049](0049-trust-loop-kill-switch-convention.md) (`enabled_cb` kill-switch convention).
- **Enforced by:** `tests/test_auto_agent_preflight_loop.py`; `tests/scenarios/test_auto_agent_preflight_scenario.py`; `tests/test_loop_wiring_completeness.py`.
- **Spec:** [docs/superpowers/specs/2026-04-25-auto-agent-hitl-preflight-design.md](../superpowers/specs/2026-04-25-auto-agent-hitl-preflight-design.md)
- **Plan:** [docs/superpowers/plans/2026-04-25-auto-agent-hitl-preflight.md](../superpowers/plans/2026-04-25-auto-agent-hitl-preflight.md)

## Context

HydraFlow's stated operating model is dark-factory: software projects meeting
the spec run lights-off, with humans paged only for raging fires. Today this
contract is broken at one specific seam — the `hitl-escalation` label fires
for ~25 distinct failure conditions across phases and caretaker loops, and
every one of them goes straight to a human. Routine, mechanically-resolvable
failures (flaky test, drifted cassette, mergeable rebase, lint regression)
demand the same human attention as genuinely novel failures.

## Decision

Add a new caretaker loop `AutoAgentPreflightLoop` that intercepts every
`hitl-escalation` issue before a human sees it. The loop:

1. Polls open `hitl-escalation` issues that don't already have `human-required`.
2. Spawns a Claude Code subprocess (via `AutoAgentRunner`, a thin `HITLRunner`
   subclass) in the issue's worktree, with a sub-label-routed prompt and a
   parameterized "lead engineer" persona.
3. Up to 3 attempts per issue; subsequent attempts receive prior-attempt
   diagnoses in their context.
4. On success: removes `hitl-escalation`, posts a diagnosis comment, links the PR.
5. On failure: applies `human-required` + diagnosis. Humans watch
   `human-required` exclusively; they no longer watch `hitl-escalation`.

Hard tool restrictions (no CI config, no force-push, no secrets, no
self-modification of principles or auto-agent code) are enforced at the
worktree-tool layer.

The deny-list (default `["principles-stuck", "cultural-check"]`) bypasses
pre-flight for sub-labels where Auto-Agent could recursively modify the system
that judges it.

Cost / wall-clock / daily-budget caps are wired but defaulted to unlimited —
observability-first, no caps until needed. A new `AutoAgentStats` System tab
tile + `/api/diagnostics/auto-agent` endpoint surface the relevant data.

## Consequences

**Positive:**
- The dark-factory contract is honored at the issue-queue layer.
- Routine toil is absorbed by the auto-agent; humans only see what the agent
  itself bails on.
- Human queue diagnoses are richer — failed pre-flights produce structured
  "what was tried, what was ruled out" comments.
- Operator gets observability into "what does HydraFlow's own agent think?"
  via dashboard + audit JSONL.

**Negative:**
- A pre-flight runs on every escalated issue, costing LLM tokens (the audit
  + dashboard make this visible).
- Pre-flight latency adds to the time-to-human for issues that genuinely
  need a human (bounded by 1 cycle ≈ ~3-10 min).
- The label state machine grows (new labels: `human-required`,
  `auto-agent-fatal`, `auto-agent-exhausted`, `auto-agent-pr-failed`,
  `cost-exceeded`, `timeout`).

**Risks:**
- Auto-agent could "fix" something incorrectly. Mitigations: hard tool
  restrictions, principles-audit deny-list, attempt cap, human review of
  the resulting PR before merge.
- Recursive self-modification risk. Mitigations: tool restrictions on
  `principles_audit_loop.py` / `auto_agent_preflight_loop.py` /
  ADR-0044/0049 implementation files.
- Runaway cost. Mitigations: caps wired into code paths (default off);
  audit + dashboard surface unusual spend immediately.

## Alternatives Considered

- **Per-call-site interception** (modify each of ~25 escalation sites to call
  a helper) — rejected: too invasive; couples auto-agent to every loop.
- **Extend `DiagnosticLoop`** to handle all escalations — rejected: conflates
  the focused diagnostic phase with general-purpose rescue; DiagnosticLoop
  would balloon.
- **Investigate-only (no fix)** — rejected: too small an unlock; doesn't honor
  the dark-factory contract.
- **Investigate + targeted fixes only** (no full agent power) — rejected:
  doesn't capture the hardest cases (refactor, novel patches); locks the system
  out of its biggest unlock.

## Source-file citations

The following files carry this ADR's decisions and must be kept in sync with any supersession:

- `src/models.py` — `StateData` fields for `auto_agent_attempts`, `auto_agent_outcomes`, `AutoAgentStateMixin`.
- `src/config.py` — `auto_agent_max_attempts`, `auto_agent_deny_list`, `auto_agent_daily_budget_usd`, `auto_agent_max_wall_clock_minutes` fields.
- `src/preflight_audit_store.py` — `PreflightAuditStore` JSONL persistence + sentry reverse-lookup.
- `src/auto_agent_runner.py` — `AutoAgentRunner` subprocess wrapper, `PreflightContext`, `PreflightDecision`.
- `src/auto_agent_preflight_loop.py` — `AutoAgentPreflightLoop._do_work` pipeline.
- `src/prompts/auto_agent/` — shared envelope (`_envelope.md`) + 9 sub-label prompt files.
- `src/dashboard_routes/diagnostics_routes.py` — `/api/diagnostics/auto-agent` endpoint.
- `src/ui/src/AutoAgentStats.jsx` — System tab tile.
- `tests/test_auto_agent_preflight_loop.py` — unit tests.
- `tests/scenarios/test_auto_agent_preflight_scenario.py` — full-loop MockWorld scenario.
- `tests/evals/auto_agent_preflight/` — adversarial corpus + eval harness.
