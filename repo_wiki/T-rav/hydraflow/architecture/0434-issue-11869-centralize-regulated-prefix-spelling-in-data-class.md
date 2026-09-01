---
id: 0434
topic: architecture
source_issue: 11869
source_phase: plan
created_at: 2026-09-01T05:42:49.576624+00:00
status: active
corroborations: 1
---

# Centralize regulated-prefix spelling in data_class_vocabulary

All `startswith("regulated-")` checks must delegate to `is_regulated_class` in `src/data_class_vocabulary.py`; never inline a second or third spelling.

- `src/prompt_gate.py` repoints its prefix check at the helper.
- `src/charter_model.py` `Charter.is_regulated` delegates to the same helper.

**Why:** Prefix-string drift (#11748) silently breaks regulated-class detection across the policy seam when each module spells it independently.
