---
id: 0690
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.858860+00:00
status: superseded
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
superseded_by: 0712
---

# ADR citations must stay bare when fixing drift — no `:Symbol` tail

When amending an ADR to fix drift, do not upgrade a bare `src/triage_phase.py` citation to a `:Symbol`-qualified one and do not add new `src/...py` citations, even if the fix references a specific function like `triage_infra_parked`.

Example: `parse_adr_file`'s `source_files` set for the ADR must stay unchanged after the edit. See also: testing — Symbol-qualify ADR citations on high-churn files to stop false drift (a distinct, proactive narrowing used on noisy registry files — not the same as widening scope mid-fix).

**Why:** widening citation scope beyond the drifted claim pulls unrelated code under that ADR's authority and breaks the narrow-scope contract regression tests check for (see `tests/regressions/test_issue_10304.py`).
