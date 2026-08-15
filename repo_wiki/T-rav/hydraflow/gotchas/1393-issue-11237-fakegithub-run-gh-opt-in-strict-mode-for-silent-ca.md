---
id: 1393
topic: gotchas
source_issue: 11237
source_phase: plan
created_at: 2026-08-15T09:27:56.205850+00:00
status: active
corroborations: 1
---

# FakeGitHub._run_gh: opt-in strict mode for silent catch-alls

When a fake's command dispatcher has a silent catch-all (`FakeGitHub._run_gh` returns `"[]"` for unrecognised shapes), add an opt-in `strict_run_gh` flag rather than changing default behavior. Route every fallthrough through one recorder helper; raise a named `UnmodelledGhCommandError` only when strict is on.

- Expose `set_strict_run_gh()`, `unmatched_gh_commands()` (defensive copy), `clear_unmatched_gh_commands()`.
- Default stays off; only the scenario under test opts in.

**Why:** Silent catch-alls produce vacuously-passing scenarios — unmodelled `gh` shapes look successful when they're simply unimplemented.
