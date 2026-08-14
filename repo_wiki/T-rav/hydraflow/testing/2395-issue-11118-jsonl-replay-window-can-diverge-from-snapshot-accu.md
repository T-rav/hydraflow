---
id: 2395
topic: testing
source_issue: 11118
source_phase: plan
created_at: 2026-08-14T10:22:06.549440+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# JSONL replay window can diverge from snapshot accumulator

When deriving window/baseline evidence by replaying `PromptTelemetry.load_inferences()`, "last `window_calls` records" assumes the JSONL tail matches the snapshot accumulator. Rotation, a short `limit`, or concurrent writes break this silently. Disclose observed-vs-claimed counts everywhere in the filed body and never assert an exact-match invariant between accumulator and record tail.

**Why:** A stale or truncated tail would otherwise produce evidence that looks authoritative but contradicts the snapshot numbers, making the filing self-confirming rather than self-refuting.
