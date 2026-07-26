---
id: 1026
topic: gotchas
source_issue: 10564
source_phase: plan
created_at: 2026-07-25T23:31:13.809595+00:00
status: active
corroborations: 1
---

# Header.jsx border-conflict test must use rerender(), not a second render()

When pinning the React style-conflict console error in `Header.test.jsx`, call `rerender()` from the same `render()` result to toggle `connected` — a second `render()` call remounts a fresh tree and the test passes vacuously even with the bug present. Also target the shared `<button>` (start/stop control), not `controlStoppingBadge` (a `<span>`): different element types remount instead of diffing styles, so that path never reproduces the warning either.

**Why:** both mistakes make the regression test green against unfixed code, defeating the pin's purpose.
