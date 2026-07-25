---
id: 0876
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:22:24.530282+00:00
status: superseded
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
superseded_by: 0898
---

# sandbox_main.py's SANDBOX_SEAMS registry needs a seam per subprocess loop

`src/mockworld/sandbox_main.py` holds an air-gap seam registry (`SANDBOX_SEAMS`) — every new subprocess-spawning loop must register a seam (config-disable, seed, or mockworld-sentinel) here.

Example: completeness is enforced by `tests/architecture/test_sandbox_seam_completeness.py`, not by the ADR citation itself.

**Why:** the seam-completeness test is the real PR-time enforcement of the air-gap invariant; ADR-0052 citations should point to it (via Enforced-by) rather than relying on drift detection over the registry file.
