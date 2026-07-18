---
id: 0159
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:34:46.627159+00:00
status: active
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
---

# Define EVENT_TO_STAGE and SOURCE_TO_STAGE mappings before skip detection

Implement event/worker-to-stage mappings together with skip detection logic — never add a mapping after skip detection is wired.

Example: define `EVENT_TO_STAGE = {...}` and `SOURCE_TO_STAGE = {...}` before the `if event in skip_set: return` guard.

**Why:** Mappings added after the early-return guard are never evaluated, making the new stage silently unreachable.
