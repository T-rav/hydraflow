---
id: 1492
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T14:38:21.767998+00:00
status: active
corroborations: 1
supersedes: 1404
---

# SANDBOX_SEAMS registry needs a seam per subprocess loop

Every new subprocess-spawning loop must register a seam (config-disable, seed, or mockworld-sentinel) in `src/mockworld/sandbox_main.py`'s `SANDBOX_SEAMS` registry.

Example: completeness is enforced by `tests/architecture/test_sandbox_seam_completeness.py`, not by the ADR citation itself.

**Why:** The seam-completeness test is the real PR-time enforcement of the air-gap invariant; ADR-0052 citations should point to it via `Enforced-by` rather than relying on drift detection over the registry file.
