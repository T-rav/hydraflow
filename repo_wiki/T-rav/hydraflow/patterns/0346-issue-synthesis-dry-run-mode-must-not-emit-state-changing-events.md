---
id: 0346
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T04:08:36.288361+00:00
status: superseded
corroborations: 1
supersedes: 0302,0303,0304,0305,0306,0307,0308,0309,0310,0311,0312,0313,0314,0315,0316,0317,0318,0319,0320,0321,0322,0323,0324,0325,0326,0327,0328,0329,0330,0331,0332,0333,0334,0335,0336,0337,0338,0339,0340,0341,0342,0343
superseded_by: 0350
---

# Dry-run mode must not emit state-changing events

Gate every side-effecting event bus publish behind `if not self.dry_run:` to ensure dry-run has no observable side effects.

Example: `if not self.dry_run: self.event_bus.publish(TRIAGE_ROUTING, ...)` — not emitted during dry-run.

**Why:** An emitted event in dry-run triggers downstream label mutations and state transitions, making dry-run non-idempotent.
