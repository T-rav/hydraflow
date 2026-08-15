---
id: 2614
topic: testing
source_issue: 11180
source_phase: plan
created_at: 2026-08-14T23:23:17.598883+00:00
status: active
corroborations: 1
---

# Include a liveness counter-pin when fixing self-retiring test pins

When rewriting a hard-coded ADR read into a self-retiring pin, add a meta-regression that deliberately writes a hard-coded ADR read into a fake tree and proves the harness catches it.

- `tests/regressions/test_issue_11180.py` builds a fake repo under `tmp_path`, copies `docs/adr` with ADR-0049 renumbered or deleted, loads the copied test module via `importlib.util.spec_from_file_location`, and invokes zero-arg `test_*` functions.
- One sub-test injects a deliberately broken hard-coded read to confirm the harness reports it.

**Why:** Without the counter-pin, deleting the pin instead of fixing it produces a vacuous green — all checks pass over an empty set.
