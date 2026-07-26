---
id: 1039
topic: gotchas
source_issue: 10579
source_phase: plan
created_at: 2026-07-26T01:24:12.531342+00:00
status: active
corroborations: 1
---

# Test React style-diff regressions with `rerender()`, not a fresh `render()`

A single `render()` call cannot reproduce React 18 style-shorthand-collision warnings — they only fire on the *diff* between two applied style objects. Regression tests (e.g. `StreamCard.borderShorthand.test.jsx`) must call `render()` once then `rerender()` with new props (e.g. `currentStage: 'review'` → `null`), with `vi.spyOn(console, 'error')` installed *before* the first render and restored in `afterEach`. Installing the spy after the first render, or replacing `rerender` with a second `render()`, makes the test pass vacuously against unfixed code.

**Why:** a regression test that can't fail on `main` gives false confidence; verify red-before-green.
