---
id: 1260
topic: gotchas
source_issue: 11085
source_phase: plan
created_at: 2026-08-14T05:58:31.318375+00:00
status: active
corroborations: 1
---

# cache_read_input_tokens drive diagnostic_fix spend, not prompt size

When investigating `diagnostic_fix` cost anomalies, inspect `cache_read_input_tokens` first. In #11085, ~80% of spend was cache reads driven by session **length**, while `prompt_chars` stayed flat at 2.8k–8k.

- Bounding turns (P1) is the correct lever; neither model-swap nor prompt-trimming applies.

**Why:** Assuming prompt size drives cost leads to the wrong fix path; cache accumulation in long sessions is the actual failure mode.
