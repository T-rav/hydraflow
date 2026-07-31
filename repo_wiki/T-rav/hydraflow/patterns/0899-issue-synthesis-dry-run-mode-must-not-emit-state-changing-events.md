---
id: 0899
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T02:33:17.844469+00:00
status: superseded
corroborations: 1
supersedes: 0841
superseded_by: 0963
---

# Dry-run mode must not emit state-changing events

Gate every side-effecting event bus publish behind `if not self.dry_run:` so dry-run mode has no observable side effects.

Example: `if not self.dry_run: self.event_bus.publish(TRIAGE_ROUTING, ...)` is not emitted during dry-run.

**Why:** An emitted event in dry-run triggers downstream label mutations and state transitions, making dry-run non-idempotent.
