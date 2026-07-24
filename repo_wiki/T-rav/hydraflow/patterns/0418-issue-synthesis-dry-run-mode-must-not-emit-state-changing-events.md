---
id: 0418
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:37:01.321228+00:00
status: active
corroborations: 1
supersedes: 0402,0403,0404,0405,0406,0407,0408,0409,0410,0411,0412,0413,0414,0415
---

# Dry-run mode must not emit state-changing events

Gate every side-effecting event bus publish behind `if not self.dry_run:` so dry-run mode has no observable side effects. Example: `if not self.dry_run: self.event_bus.publish(TRIAGE_ROUTING, ...)` is not emitted during dry-run. **Why:** an emitted event in dry-run triggers downstream label mutations and state transitions, making dry-run non-idempotent.
