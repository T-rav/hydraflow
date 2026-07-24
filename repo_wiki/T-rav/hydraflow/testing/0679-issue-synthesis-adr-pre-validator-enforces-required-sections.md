---
id: 0679
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.841099+00:00
status: active
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
---

# ADR pre-validator enforces required sections

All ADRs must pass `tests/test_adr_pre_validator.py`, which enforces required sections (Status, Context, Decision, Consequences) and valid status values.

Example: see also architecture — ADR number collision and README guards.

**Why:** Missing sections or invalid status values make ADRs non-machine-readable, breaking automated drift detection and the ADR README completeness guard.
