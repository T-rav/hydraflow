---
id: 1843
topic: patterns
source_issue: 11133
source_phase: plan
created_at: 2026-08-14T12:41:23.460357+00:00
status: superseded
corroborations: 1
superseded_by: 1940
---

# Carry baseline forward for under-sampled telemetry sources

When gating `SkillPromptEvalLoop` filings on a minimum window size, overwrite the stored baseline only when the window met the floor (or no prior entry exists, or `delta_calls <= 0` for counter resets). Otherwise keep the prior entry.

- Under-sampled source: skip filing, **do not advance baseline** → next tick measures a wider window.
- Well-sampled source: overwrite baseline with current snapshot.
- Counter reset (`delta_calls <= 0`): overwrite to avoid pinning forever.

**Why:** A plain skip on every tick resets the window each time, so low-volume sources become permanently unmeasurable.
