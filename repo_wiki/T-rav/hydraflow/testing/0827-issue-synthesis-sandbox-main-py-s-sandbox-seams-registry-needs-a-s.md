---
id: 0827
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:43:21.203743+00:00
status: active
corroborations: 1
supersedes: 0754,0755,0756,0757,0758,0759,0760,0761,0762,0763,0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797
---

# sandbox_main.py's SANDBOX_SEAMS registry needs a seam per subprocess loop

`src/mockworld/sandbox_main.py` holds an air-gap seam registry (`SANDBOX_SEAMS`) — every new subprocess-spawning loop must register a seam (config-disable, seed, or mockworld-sentinel) here.

Example: completeness is enforced by `tests/architecture/test_sandbox_seam_completeness.py`, not by the ADR citation itself.

**Why:** the seam-completeness test is the real PR-time enforcement of the air-gap invariant; ADR-0052 citations should point to it (via Enforced-by) rather than relying on drift detection over the registry file.
