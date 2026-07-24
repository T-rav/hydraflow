---
id: 0449
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:37:14.510559+00:00
status: superseded
corroborations: 1
supersedes: 0432,0433,0434,0435,0436,0437,0438,0439,0440,0441,0442,0443,0444,0445
superseded_by: 0463
---

# Dry-run mode must not emit state-changing events

Gate every side-effecting event bus publish behind `if not self.dry_run:` so dry-run mode has no observable side effects.

Example: `if not self.dry_run: self.event_bus.publish(TRIAGE_ROUTING, ...)` is not emitted during dry-run.

**Why:** an emitted event in dry-run triggers downstream label mutations and state transitions, making dry-run non-idempotent.
