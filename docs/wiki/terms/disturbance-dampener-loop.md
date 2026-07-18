---
id: "01KWFR9AWM3NX19D0C1W10NNMK"
name: "DisturbanceDampenerLoop"
kind: "loop"
bounded_context: "shared-kernel"
code_anchor: "src/disturbance_dampener_loop.py:DisturbanceDampenerLoop"
aliases: []
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-01T21:10:16.212647+00:00"
updated_at: "2026-07-01T21:10:16.212839+00:00"
---

## Definition

The burn-down actuator half of the Disturbance Dampener (ADR-0095). Each tick it runs every registered dimension's ViolationDetector, loads that dimension's baseline, and selects a capped, smallest-first, deduped batch of BurndownUnits (one per dimension+file). For each unit it dispatches a coding agent via generate_and_open_pr_async to fix the violations in that file and prune the corresponding baseline entries, opening one PR per file (Pattern A). It follows SandboxFailureFixerLoop's caretaker shape: LoopDeps wiring, a kill-switch, max-PRs-per-tick saturation, per-unit attempt caps, and dedup so an already-opened unit is not redispatched.

## Invariants

- Every per-unit exception handler calls reraise_on_credit_or_bug before recording a failure, so a credit-exhaustion signal is never absorbed as a per-file crash.
- A unit is only marked opened (and deduped) after generate_and_open_pr_async reports status == 'opened'; a crashed or skipped unit leaves the unit eligible for retry up to auto_agent_max_attempts.
