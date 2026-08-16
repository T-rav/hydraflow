---
id: 3462
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T08:05:58.271417+00:00
status: superseded
corroborations: 1
supersedes: 3325
superseded_by: 3609
---

# DedupStore key shape: <loop>:<check>:<entity>:<ISO-year>-W<week>

Construct `DedupStore` keys as `skill_prompt_eval:<check_name>:<source>:<ISO-year>-W<week>` so a second tick within the same ISO week is a no-op but the same sustained drift files again in the next week. Use a `__median__` sentinel for fleet-wide metrics that have no per-source entity.

**Why:** Keys without the ISO-week bucket either fire every tick (no dedup) or fire only once ever (no re-alert on sustained drift); the time bucket is what makes the actuator advisory rather than spammy.
