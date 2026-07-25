---
id: 0501
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T06:12:20.632882+00:00
status: active
corroborations: 1
supersedes: 0481,0482,0483,0484,0485,0486,0487,0488,0489,0490,0491,0492,0493,0494,0495,0496,0497,0498
---

# Dry-run mode must not emit state-changing events

Gate every side-effecting event bus publish behind `if not self.dry_run:` so dry-run mode has no observable side effects.

Example: `if not self.dry_run: self.event_bus.publish(TRIAGE_ROUTING, ...)` is not emitted during dry-run.

**Why:** an emitted event in dry-run triggers downstream label mutations and state transitions, making dry-run non-idempotent.
