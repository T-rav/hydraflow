---
id: 0586
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:08:06.328708+00:00
status: active
corroborations: 1
supersedes: 0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583
---

# Dry-run mode must not emit state-changing events

Gate every side-effecting event bus publish behind `if not self.dry_run:` so dry-run mode has no observable side effects.

Example: `if not self.dry_run: self.event_bus.publish(TRIAGE_ROUTING, ...)` is not emitted during dry-run.

**Why:** an emitted event in dry-run triggers downstream label mutations and state transitions, making dry-run non-idempotent.
