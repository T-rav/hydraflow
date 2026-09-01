---
id: 2796
topic: testing
source_issue: 11863
source_phase: plan
created_at: 2026-09-01T06:14:33.638491+00:00
status: active
corroborations: 1
---

# Runtime-scan fixture trees; never mirror them in hardcoded lists

Materialize fixture trees by scanning the fixture root at runtime. Do not maintain a parallel hardcoded list of expected files. Example: `src/mockworld/sandbox_main.py::materialize_demo_repo()` scans `tests/fixtures/demo_org/` so adding a file there changes what is materialized with no list edit.

**Why:** A hardcoded list mirroring a fixture is the #11669 class of drift bug — the fixture drifts, the list doesn't, and materialization silently misses files.
