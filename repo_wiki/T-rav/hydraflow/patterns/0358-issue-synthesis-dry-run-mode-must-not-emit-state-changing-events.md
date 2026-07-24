---
id: 0358
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T18:01:25.882321+00:00
status: superseded
corroborations: 1
supersedes: 0350,0350,0351,0352,0353,0354,0355
superseded_by: 0364
---

# Dry-run mode must not emit state-changing events

Gate every side-effecting event bus publish behind `if not self.dry_run:` so dry-run has no observable side effects.

Example: `if not self.dry_run: self.event_bus.publish(TRIAGE_ROUTING, ...)` — not emitted during dry-run.

**Why:** An emitted event in dry-run triggers downstream label mutations and state transitions, making dry-run non-idempotent.
