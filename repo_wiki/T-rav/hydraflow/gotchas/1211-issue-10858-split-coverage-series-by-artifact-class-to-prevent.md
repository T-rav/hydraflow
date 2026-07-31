---
id: 1211
topic: gotchas
source_issue: 10858
source_phase: plan
created_at: 2026-07-31T01:20:45.119606+00:00
status: active
corroborations: 1
---

# Split coverage series by artifact class to prevent clone swamping

When multiple templates share an inlined partial (e.g. 16 `prompts/auto_agent/*.md` render through `preflight.runner.render_prompt` with a shared `_envelope.md`), their rendered texts are near-duplicates. Folding them into a single `criterion_fail_rates` series lets clones mask a real regression.

Report severity/criterion series **split by artifact class** (`builder_coverage` vs `template_coverage`) in `PromptFitness.as_dict()`.

**Why:** Aggregate skew from duplicate renders silently hides per-prompt regressions in the fleet-level numbers.
