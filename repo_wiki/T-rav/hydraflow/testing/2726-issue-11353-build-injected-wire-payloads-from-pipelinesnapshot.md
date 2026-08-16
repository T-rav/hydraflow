---
id: 2726
topic: testing
source_issue: 11353
source_phase: plan
created_at: 2026-08-16T14:57:57.978705+00:00
status: active
corroborations: 1
---

# Build injected wire payloads from PipelineSnapshot.model_dump(), not literals

When injecting a `/api/pipeline` response body in tests, construct it from `PipelineSnapshot(stages=...).model_dump()`, never a hand-written literal dict. If `PipelineSnapshot` gains a field (e.g. `ready`), a literal dict silently stops modelling reality and the test proves nothing.

**Why:** Prevents wire-payload rot where a schema change makes the injected fixture diverge from real backend output, giving false confidence.
