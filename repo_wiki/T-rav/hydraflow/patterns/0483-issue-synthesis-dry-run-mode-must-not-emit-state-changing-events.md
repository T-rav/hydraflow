---
id: 0483
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T22:03:19.139839+00:00
status: active
corroborations: 1
supersedes: 0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480
---

# Dry-run mode must not emit state-changing events

Gate every side-effecting event bus publish behind `if not self.dry_run:` so dry-run mode has no observable side effects.

Example: `if not self.dry_run: self.event_bus.publish(TRIAGE_ROUTING, ...)` is not emitted during dry-run.

**Why:** an emitted event in dry-run triggers downstream label mutations and state transitions, making dry-run non-idempotent.
