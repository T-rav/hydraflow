---
id: 0164
topic: architecture
source_issue: 10403
source_phase: plan
created_at: 2026-07-24T05:36:17.563595+00:00
status: active
corroborations: 1
---

# Concept-scatter sensor (#10104) flags cross-module duplicate ops like `append`

A PROVISIONAL sensor detects when independent modules (`src.audit`, `src.escape`, `src.intervention`, `src.erosion`) each define their own copy of the same operation — e.g. all four defined a hand-rolled `append` for JSONL persistence. It surfaces the scatter as a signal, not an auto-fix; unifying is a human-judgment call (tracked via issue #10403). When touching one of these modules, check whether the sensor has flagged a sibling duplication before adding another parallel implementation.

**Why:** prevents a fifth copy-paste store from being added before the existing four get unified.
