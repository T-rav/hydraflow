---
id: 3156
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T04:41:06.039392+00:00
status: active
corroborations: 1
supersedes: 3022
---

# Carry baseline forward for under-sampled telemetry sources

When gating `SkillPromptEvalLoop` filings on minimum window size, overwrite the stored baseline only when the window met the floor, no prior entry exists, or `delta_calls <= 0` (counter reset). Otherwise keep the prior entry.

Example: Under-sampled source → skip filing, do not advance baseline (next tick measures wider window); well-sampled → overwrite; counter reset → overwrite to avoid pinning forever.

**Why:** A plain skip on every tick resets the window each time, so low-volume sources become permanently unmeasurable.
