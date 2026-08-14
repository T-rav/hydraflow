---
id: "01KZ1RA3CGWE9H5XX59XH66DQF"
name: "GoalSupervisorLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/goal_supervisor_loop.py:GoalSupervisorLoop"
aliases: ["goal supervisor loop", "tier-2 goal supervisor", "goal supervisor", "mini-me supervisor"]
related: [{"kind": "depends_on", "target": "01JZ9FK3C0M01HYR42BF11W0A1"}, {"kind": "depends_on", "target": "01KYM003P7D6GN4KSS1X9RBEXQ"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K2"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K5"}, {"kind": "depends_on", "target": "01JZ9FK3C0M03HYR42BF33W0C3"}, {"kind": "depends_on", "target": "01KQV37D10M06PGF32CF77W6K4"}, {"kind": "depends_on", "target": "01KYW34KGZNXKF5N1TNB7VB731"}, {"kind": "depends_on", "target": "01KWDRENTS7VACCW9PDA7Y488H"}, {"kind": "implements", "target": "01KQV37D10M06PGF32CF77W6K5"}]
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-08-02T00:00:00.000000+00:00"
updated_at: "2026-08-14T05:32:18.123535+00:00"
---

## Definition

Tier-2 (meta-observability) caretaker loop that formalizes the by-hand "keep the factory alive & healthy" monitor (ADR-0124, #10733). Ticks on a cadence, assembles a read-only `HealthSnapshot` from the existing Tier-1 signals (per-loop heartbeats, credit-failover state, boot-SHA staleness, the event-loop watchdog marker, the second-order vitals verdict), hands it to a Fable agent (`claude-fable-5`) under the standing goal, and records a `SupervisorObservation` (assessment · insights · nudges-taken · escalations · deferred) to the append-only `supervisor_thread.jsonl` + the event bus. Authority is **watch + surface + NUDGE** only — a small reversible allowlist; everything with blast radius is surfaced, never self-done. The load-bearing classify / known-incident / nudge-vs-escalate / give-up-window logic is pure and unit-tested in `supervisor_observation`. Ships default OFF.

## Invariants

- Reuses Tier-1 signals; the snapshot never re-detects and never mutates.
- Nudge allowlist is small and explicit (`NUDGE_ALLOWLIST`); everything else escalates (surface, never self-do) — mirrors `docs/standards/factory_autonomy`.
- A nudge carries a one-line root-cause diagnosis; a cause-less action is dropped as noise.
- Bounded retries then escalate: an incident is nudged ≤ `GIVEUP_CAP` times (give-up window, attempt ledger persisted across ticks), then escalates — never infinite-retry.
- Verify + re-arm: a nudge is pending until a later tick confirms its condition cleared (`reconcile_ledger`); a still-present incident counts toward the give-up window.
- Healthy snapshot → no-op without consulting the Fable agent (cost control).
- Kill-switch is via `enabled_cb("goal_supervisor")` and the `goal_supervisor_loop_enabled` deploy-time gate (ADR-0049).
- Tier separation: registered standalone (not folded into `HealthMonitorLoop`) so no LLM sits in the deterministic Tier-1 kernel (ADR-0124).
