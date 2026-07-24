---
id: 0622
topic: testing
source_issue: 10386
source_phase: plan
created_at: 2026-07-24T04:38:03.777843+00:00
status: superseded
corroborations: 1
superseded_by: 0632
---

# sandbox_main.py's SANDBOX_SEAMS registry needs a seam per subprocess loop

`src/mockworld/sandbox_main.py` holds an air-gap seam registry (`SANDBOX_SEAMS`) — every new subprocess-spawning loop must register a seam (config-disable, seed, or mockworld-sentinel) here. Completeness is enforced by `tests/architecture/test_sandbox_seam_completeness.py`, not by the ADR citation itself.

**Why:** the seam-completeness test is the real PR-time enforcement of the air-gap invariant; ADR-0052 citations should point to it (via Enforced-by) rather than relying on drift detection over the registry file.
