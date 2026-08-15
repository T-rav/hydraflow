---
id: 2803
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T11:44:51.613849+00:00
status: active
corroborations: 1
supersedes: 2674
---

# Dry-run mode must not emit state-changing events

Gate every side-effecting event bus publish behind `if not self.dry_run:` so dry-run mode has no observable side effects.

Example: `if not self.dry_run: self.event_bus.publish(TRIAGE_ROUTING, ...)` is not emitted during dry-run.

**Why:** An emitted event in dry-run triggers downstream label mutations and state transitions, making dry-run non-idempotent.
