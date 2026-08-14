---
id: 2258
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:36.857830+00:00
status: superseded
corroborations: 1
supersedes: 2113
superseded_by: 2448
---

# SANDBOX_SEAMS registry needs a seam per subprocess loop

Every new subprocess-spawning loop must register a seam (config-disable, seed, or mockworld-sentinel) in `src/mockworld/sandbox_main.py`'s `SANDBOX_SEAMS` registry.

Example: completeness is enforced by `tests/architecture/test_sandbox_seam_completeness.py`, not by the ADR citation itself.

**Why:** The seam-completeness test is the real PR-time enforcement of the air-gap invariant; ADR-0052 citations should point to it via Enforced-by.
