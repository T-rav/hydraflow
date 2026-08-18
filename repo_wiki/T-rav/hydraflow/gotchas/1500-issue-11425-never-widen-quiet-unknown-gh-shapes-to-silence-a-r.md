---
id: 1500
topic: gotchas
source_issue: 11425
source_phase: plan
created_at: 2026-08-18T04:29:33.971225+00:00
status: active
corroborations: 1
---

# Never widen _QUIET_UNKNOWN_GH_SHAPES to silence a red

`#11372` makes unmodelled `gh` shapes raise; every shape a promoted Port method retires must leave `_QUIET_UNKNOWN_GH_SHAPES` in `src/mockworld/fakes/fake_github.py` untouched.
- If a promotion surfaces a red from an unknown shape, fix the fake or the call site — do not add the shape to the allowlist.
**Why:** Widening the allowlist converts a fail-loud signal into silent drift; the whole point of the guard is that unmodelled shapes raise rather than quietly pass.
