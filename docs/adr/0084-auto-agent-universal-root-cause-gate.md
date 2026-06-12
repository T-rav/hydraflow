# ADR-0084: Auto-Agent as a Universal, Persistent, Root-Cause HITL Gate

- **Status:** Proposed
- **Date:** 2026-06-12
- **Supersedes:** none
- **Superseded by:** none
- **Amends:** [ADR-0050](0050-auto-agent-hitl-preflight.md) (Auto-Agent HITL Pre-Flight Loop) — keeps its architecture, tightens its escalation contract.
- **Related:** [ADR-0002](0002-labels-as-state-machine.md) (label state machine); [ADR-0029](0029-caretaker-loop-pattern.md) (caretaker loop pattern); [ADR-0044](0044-hydraflow-principles.md) (principles audit, recursion safety); [ADR-0045](0045-trust-architecture-hardening.md) (`hitl-escalation`); [ADR-0049](0049-trust-loop-kill-switch-convention.md) (`enabled_cb` kill-switch); [ADR-0032](0032-per-repo-wiki-knowledge-base.md) (wiki for learned playbooks).
- **Enforced by (planned):** `tests/test_auto_agent_preflight_loop.py`; `tests/test_escalation_mixin.py`; `tests/test_pipeline_human_required_guard.py`; `tests/scenarios/test_auto_agent_convergence_scenario.py`; `tests/test_loop_wiring_completeness.py`.

## Context

[ADR-0050](0050-auto-agent-hitl-preflight.md) introduced the `AutoAgentPreflightLoop` to honour the dark-factory contract: intercept every `hitl-escalation` issue, let an auto-agent ("emulated Travis") attempt a fix, and page a human only for genuinely novel failures. The architecture is sound and shipped. **In practice the gate is too timid**, so the meta-pattern it was meant to kill keeps recurring — this very session resolved four instances of it by hand:

- **ADR-drift** false positives (#9304–#9309), **fake-coverage** false positives (#9400/#9403), **trust anomalies** (#9222/#9223/#9275), and the **retrospective stale-insight** HITL dead-end (#9227, fixed in #9431). Every one is *the factory escalating to a human something it should have auto-resolved or never escalated.*
- **#9275 is the smoking gun:** the auto-agent fired, diagnosed *"all background tasks confirmed clean state"*, returned `needs_human` **on attempt 1 with no fix and no retry**, and the issue then sat until a human closed it.

Five concrete gaps (mapped against the live code) explain the timidity:

1. **One-shot bail.** The 3-attempt budget is *inter-issue*, not used to retry a single weak/transient bail. `parse_agent_response` *defaults* to `needs_human` on any malformed output. There is no `retry` outcome and no confidence/blocked-reason signal, so a transient "context gather failed" is indistinguishable from a genuine human-only blocker.
2. **Playbook-limited → cannot fix novel issues.** Only five phase specialists (plan/implement/review/discover/triage) plus a generic `_default`. The ~20 `*-stuck` caretaker domains (fake-coverage, adr-drift, flaky, wiki-rot, shadow-drift, …) fall to `_default` with generic guidance — a weak attempt that converts straight to `needs_human`.
3. **Issues cycle.** `human-required` is invisible to the core phases and absent from `all_pipeline_labels`, so it survives `swap_pipeline_labels`. An exhausted issue keeps its origin label, re-enters plan→diagnose→hitl→auto-agent, and repeats. There is **no global escalation cap**.
4. **Not everything routes through the gate.** Routing keys off `hitl-escalation`; the deny-list and any future loop that forgets to pair `hitl-escalation` with its `*-stuck` label skip the agent entirely. The escalation pattern is copy-pasted across 10+ loops with no shared helper, so drift is inevitable.
5. **No root-cause convergence or learning.** The agent fixes the symptom issue, never confirms the *root cause* won't recur, and discards successful fixes (no learned-playbook cache).

The operating principle we want: **almost nothing reaches a human.** A human is paged only for a true "on-fire" condition — never for routine, mechanically- or agentically-resolvable toil, and never because the gate gave up early.

## Decision

Make the Auto-Agent a **universal, persistent, root-cause** gate. Five pillars.

### A. Universal interception — every escalation hits the auto-agent first

- Extract a shared `BaseEscalationMixin` used by **all** caretaker loops; it always files `hitl-escalation` + exactly one domain `*-stuck` sub-label, and owns the reconcile-on-close lifecycle. This guarantees the single routing chokepoint and removes the copy-paste drift.
- Add a central **stuck-label registry** in config (name → policy: `auto_agent_allowed`, `domain_context_pack`, `description`). A pre-flight validator rejects/flags any `hitl-escalation` issue that lacks a registered sub-label, so a new producer cannot silently bypass the gate.
- Shrink the bypass deny-list to the **recursion-critical minimum** (self-judgment: `principles-stuck`, `cultural-check`). The auto-agent's *own* code is already protected by tool-layer path restrictions, so it need not be on a label deny-list.

### B. Convergence loop — retry to root cause, escalate only when truly blocked

- Add a **`retry`** outcome to `PreflightResult.status`, distinct from `needs_human`.
- The agent's `<diagnosis>` gains a **`confidence`** (`high`|`medium`|`low`) and a **`blocked_reason`** enum: `transient` | `insufficient_context` | `needs_human_decision` | `needs_credentials` | `needs_permissions` | `unsafe` | `none`.
- `apply_decision` escalates to `human-required` **only** when `blocked_reason ∈ {needs_human_decision, needs_credentials, needs_permissions, unsafe}` at `high` confidence. Everything else (`transient`, `insufficient_context`, low-confidence) becomes **`retry`**: the loop keeps the issue, broadens context (more git/Sentry/wiki/test history) and a *different* approach on the next cycle.
- Replace the flat 3-strike cap with a **graduated escalation budget** (probe → specialist → broadened-context → adversarial self-review), each attempt distinct.
- Parse robustness: a structured fallback (scan the diagnosis for blocker keywords) instead of defaulting to `needs_human`.

### C. Anti-cycle guardrails — bounded, never infinite

- Add `human-required` to `all_pipeline_labels` so a successful HITL correction's swap clears it.
- The core phases (plan/implement/review/triage) **skip** any task tagged `human-required`.
- Add a **global per-issue escalation counter** in `StateTracker`, incremented on *every* escalation regardless of source/phase. When an issue exceeds the cap (default 6), it is forced to true-HITL with a "genuinely stuck after N diverse attempts" comment — this is the legitimate true-HITL trigger, and the cycle stops.

### D. Novel-issue capability — a generic root-cause resolver

- Replace the weak `_default` with a first-class **root-cause resolver** persona: *form a hypothesis → make the change → verify (tests/repro) → iterate*. It is **not** limited to known shapes.
- Feed it lightweight, per-domain **context packs** (what each caretaker loop checks and where its code lives) keyed off the stuck-label registry, so it is grounded for any of the ~20 domains without a hand-written playbook each.

### E. Learning + observability

- On a confirmed resolution, cache the successful pattern (conditions + fix shape) to the per-repo wiki ([ADR-0032](0032-per-repo-wiki-knowledge-base.md)); probe the cache on the first attempt for a fast path on routine recurrences.
- Always post a structured **escalation-reason** comment ("what was tried, what was ruled out, why a human is needed") before any issue reaches a human.

### True-HITL is reserved for exactly three "on-fire" conditions

An issue reaches `human-required` only when:
1. **Safety tripwire** — the fix requires editing recursion-critical/principles/CI/secrets code, or an irreversible/destructive action.
2. **Human-only blocker** — a product/policy decision, missing credentials, or repo permissions the agent cannot obtain (high confidence).
3. **Global cap tripped** — genuinely stuck after many diverse attempts.

Everything else loops inside the auto-agent until resolved.

## Consequences

**Positive:**
- The dark-factory contract is actually honoured: the human queue collapses to genuine fires.
- Recurring false-positive/dead-end escalations (this session's whole theme) are absorbed automatically.
- Root-cause focus + learned playbooks reduce recurrence over time, not just per-issue.

**Negative:**
- More auto-agent cycles per issue → more LLM spend. Mitigated by the graduated budget, learned-playbook fast path, and the existing daily-budget cap + audit/dashboard visibility.
- Time-to-human for genuine fires grows by the convergence budget. Acceptable: true fires are rare and the global cap bounds the delay.

**Risks (this subsystem fixes the factory — recursion sensitivity is paramount):**
- *Auto-agent loops forever / burns budget.* Mitigations: global escalation cap (C), graduated budget (B), daily-budget gate, mid-run cost watchdog.
- *Auto-agent "fixes" something wrong with more autonomy.* Mitigations: unchanged tool-layer restrictions, human review of every resulting PR before merge, the safety tripwire, and the recursion-critical deny-list.
- *Retry masks a real human-needed issue.* Mitigation: the `blocked_reason` taxonomy routes true human-only blockers straight out; only `transient`/`insufficient_context`/low-confidence retry.

## Alternatives Considered

- **Leave ADR-0050 as-is, fix false positives at each producer** (what we did by hand this session) — rejected: treats symptoms, not the gate; the meta-pattern recurs with every new loop.
- **More hand-written playbooks per domain** — rejected: doesn't scale to novel issues and re-creates the playbook-limited gap; the generic resolver + context packs subsume it.
- **Raise the flat attempt cap to N** — rejected: more weak `_default` passes is not convergence; without the `retry`/`blocked_reason` distinction it just delays the same bail and burns budget.
- **Make true-HITL impossible (no human path)** — rejected: the three on-fire conditions genuinely need a human; the goal is *rare*, not *never*.

## Rollout (staged; each stage is independently shippable)

1. **PR-1 — Cycle safety (re-entry break):** `human-required` filtering in core phases (skip in `IssueStore._take_from_queue`) + added to `all_pipeline_labels` so it clears on a successful HITL correction. This alone eliminates the unbounded autonomous cycle (a corrected issue re-enters clean; a blocked one is never re-pulled). (Highest value, lowest risk.)
2. **PR-2 — Convergence:** `retry` outcome + `confidence`/`blocked_reason` + intra-issue retry; parse robustness.
3. **PR-3 — Universal routing + global cap:** `BaseEscalationMixin` + central stuck-label registry + bypass-validator; deny-list shrink. The shared mixin is the single escalation chokepoint, so the **global per-issue escalation counter → forced true-HITL at cap** lands here (where it can count *every* escalation cleanly) rather than being bolted onto the ~7 current escalation sites.
4. **PR-4 — Novel resolver + learning:** generic root-cause persona + domain context packs + learned-playbook wiki cache.

Each stage ships the full test pyramid (unit + MockWorld scenario + sandbox e2e) per `docs/standards/testing/`.

## Source-file citations

The following files carry this ADR's decisions and must be kept in sync with any supersession:

- `src/auto_agent_preflight_loop.py:AutoAgentPreflightLoop` — the gate loop; gains graduated budget, `retry` handling, and the global-cap → true-HITL transition.
- `src/preflight/decision.py:apply_decision` — escalates to `human-required` only on the three on-fire conditions; maps the new `retry` status via `_LABEL_MAP`.
- `src/preflight/agent.py:run_preflight` — emits `confidence` + `blocked_reason`; parse-robust fallback instead of defaulting to `needs_human`.
- `src/preflight/runner.py:parse_agent_response` — structured fallback parsing.
- `src/preflight/context.py:PreflightContext` — domain context packs + context-sufficiency gating.
- `src/models.py:StateData` — new `escalation_attempts: dict[str, int]` (global per-issue counter).
- `src/config.py:HydraFlowConfig` — `auto_agent_skip_sublabels` (shrunk), stuck-label registry, global escalation cap field.
- `src/issue_store.py:IssueStore` — `human-required` made visible so core phases skip it.
- `src/pr_manager.py:swap_pipeline_labels` — clears `human-required` via `all_pipeline_labels`.
- `src/base_background_loop.py:BaseBackgroundLoop` — host for the shared `BaseEscalationMixin`.
