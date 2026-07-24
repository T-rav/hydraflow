---
id: 0701
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.877045+00:00
status: superseded
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
superseded_by: 0712
---

# sandbox_main.py's SANDBOX_SEAMS registry needs a seam per subprocess loop

`src/mockworld/sandbox_main.py` holds an air-gap seam registry (`SANDBOX_SEAMS`) — every new subprocess-spawning loop must register a seam (config-disable, seed, or mockworld-sentinel) here.

Example: completeness is enforced by `tests/architecture/test_sandbox_seam_completeness.py`, not by the ADR citation itself.

**Why:** the seam-completeness test is the real PR-time enforcement of the air-gap invariant; ADR-0052 citations should point to it (via Enforced-by) rather than relying on drift detection over the registry file.
