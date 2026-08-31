---
id: 2786
topic: testing
source_issue: 11548
source_phase: plan
created_at: 2026-08-30T10:39:26.773393+00:00
status: active
corroborations: 1
---

# Parametrize-collapse must use pytest.param(id=) to preserve node ids

When collapsing a four-member `@parametrize` group into one table, wrap each row in `pytest.param(..., id=<old test name>)`. This keeps every case reachable as a pytest node id and keeps `--collect-only` counts flat.

- `tests/test_config_docker.py`, `tests/test_control_register.py` — 13 value-varying tables collapsed in batch 7's discipline.
- Without `id=`, downstream tools that select by test name break silently.

**Why:** Preserving node ids is the only proof the collapse didn't drop a case; the ratchet measures copies, not semantics.
