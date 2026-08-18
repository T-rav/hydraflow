---
id: 2743
topic: testing
source_issue: 11415
source_phase: plan
created_at: 2026-08-18T03:26:10.006522+00:00
status: active
corroborations: 1
---

# Keep _FAKE_PAIRS as list[tuple[type, type]] for pin liveness

The `_FAKE_PAIRS` registry in `tests/test_mockworld_fakes_conformance.py` must stay a module-level list of 2-tuples of types.

- Reference may be a Port Protocol or a concrete production class — comparison is identical.
- Do not convert to a dataclass or 3-tuple.

**Why:** The `tests/regressions/test_issue_11415.py` pin discovers the registry structurally by shape; changing the container type breaks the liveness guard for the wrong reason.
