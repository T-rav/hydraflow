---
id: 2280
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-15T01:03:09.934151+00:00
status: superseded
corroborations: 1
supersedes: 2164
superseded_by: 2400
---

# Carry baseline forward for under-sampled telemetry sources

When gating `SkillPromptEvalLoop` filings on minimum window size, overwrite the stored baseline only when the window met the floor, no prior entry exists, or `delta_calls <= 0` (counter reset). Otherwise keep the prior entry.

Example: Under-sampled source → skip filing, do not advance baseline (next tick measures wider window); well-sampled → overwrite; counter reset → overwrite to avoid pinning forever.

**Why:** A plain skip on every tick resets the window each time, so low-volume sources become permanently unmeasurable.
