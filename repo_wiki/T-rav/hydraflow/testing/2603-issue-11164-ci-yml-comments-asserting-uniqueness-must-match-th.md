---
id: 2603
topic: testing
source_issue: 11164
source_phase: plan
created_at: 2026-08-14T18:58:35.986563+00:00
status: active
corroborations: 1
---

# ci.yml comments asserting uniqueness must match the parsed workflow

Any comment in `.github/workflows/ci.yml` claiming a job *uniquely* holds a property (e.g. `fetch-depth: 0`, a specific step) must be verifiable against the parsed workflow. The `audit` job comment claiming it uniquely has full-history checkout was false — `arch` also sets `fetch-depth: 0`.

**Why:** Stale uniqueness comments mislead future edits and can hide that a step like `make console-conformance` was placed in a job for a reason that no longer holds.
