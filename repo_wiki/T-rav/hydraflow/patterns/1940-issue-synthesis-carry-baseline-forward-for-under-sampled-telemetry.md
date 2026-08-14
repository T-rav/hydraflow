---
id: 1940
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T14:29:27.148448+00:00
status: superseded
corroborations: 1
supersedes: 1843
superseded_by: 2048
---

# Carry baseline forward for under-sampled telemetry sources

When gating `SkillPromptEvalLoop` filings on a minimum window size, overwrite the stored baseline only when the window met the floor (or no prior entry exists, or `delta_calls <= 0` for counter resets). Otherwise keep the prior entry.

- Under-sampled source: skip filing, **do not advance baseline** → next tick measures a wider window.
- Well-sampled source: overwrite baseline with current snapshot.
- Counter reset (`delta_calls <= 0`): overwrite to avoid pinning forever.

**Why:** A plain skip on every tick resets the window each time, so low-volume sources become permanently unmeasurable.
