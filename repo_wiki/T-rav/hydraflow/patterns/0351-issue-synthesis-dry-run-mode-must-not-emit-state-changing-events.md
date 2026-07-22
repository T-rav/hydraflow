---
id: 0351
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T12:09:24.765279+00:00
status: superseded
corroborations: 1
supersedes: 0344,0345,0346,0347,0349
superseded_by: 0356
---

# Dry-run mode must not emit state-changing events

Gate every side-effecting event bus publish behind `if not self.dry_run:` to ensure dry-run has no observable side effects.

Example: `if not self.dry_run: self.event_bus.publish(TRIAGE_ROUTING, ...)` — not emitted during dry-run.

**Why:** An emitted event in dry-run triggers downstream label mutations and state transitions, making dry-run non-idempotent.
