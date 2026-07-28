---
id: 0257
topic: architecture
source_issue: 10785
source_phase: plan
created_at: 2026-07-28T09:16:36.126398+00:00
status: active
corroborations: 1
---

# no-inline-style.ratchet.test.js forbids inline styles in src/operator

Every new component under `src/ui/src/operator/` must use `makeStyles(t)` + `useTokens()` or style primitives from the first commit. No `style={{...}}` JSX attributes, no hex colour literals.

- The ratchet test is at zero and must stay at zero.
- Gate runs via `make quality`.

**Why:** Adding a single inline style or colour literal trips the ratchet and fails the quality gate, blocking merge.
