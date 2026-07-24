---
id: 0390
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:23:13.605063+00:00
status: active
corroborations: 1
supersedes: 0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387
---

# Dry-run mode must not emit state-changing events

Gate every side-effecting event bus publish behind `if not self.dry_run:` so dry-run has no observable side effects.

Example: `if not self.dry_run: self.event_bus.publish(TRIAGE_ROUTING, ...)` — not emitted during dry-run.

**Why:** An emitted event in dry-run triggers downstream label mutations and state transitions, making dry-run non-idempotent.
