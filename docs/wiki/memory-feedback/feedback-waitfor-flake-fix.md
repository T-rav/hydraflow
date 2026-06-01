---
source: feedback_waitfor_flake_fix.md
name: feedback_waitfor_flake_fix
description: Fix the recurring vitest "assert right after act(async render)" timing-race flake with waitFor, not CI re-runs
status: pending
issue: null
promoted_in: null
wontfix_reason: null
created: '2026-05-31'
---

A vitest test that asserts state **synchronously right after** `await act(async () => render(...))`, when the trigger fires on a **macrotask** (e.g. a MockWebSocket whose `constructor` does `setTimeout(() => this.onopen(), 0)`), is a timing race: `act()` flushes microtasks + effects but does NOT await `setTimeout(0)`. CI (slower/loaded runners) loses the race intermittently; local full-suite often wins it → looks like a flake that "passes locally."

**Why:** the assertion runs before the async onopen → setState → re-render lands.

**How to apply:** wrap the assertion in `waitFor(() => { ... })` (import from `@testing-library/react`) so it polls until the condition holds or times out. This is NOT loosening — same assertion, just correctly awaited. Fix the ROOT, don't gamble on `gh run rerun --failed` — the flake recurs across the whole stack and on staging.

Seen 2026-06-01 on `HydraFlowContext.test.jsx > sets data-connected on body when websocket connects` (WS-RT #9109). Verified stable 5/5 after the fix. Verify CI's real runner with `node ./scripts/run-vitest.cjs run <file>` (the wrapper isolates differently than raw `npx vitest run <file>`, which can itself flake). NOTE for stacked PRs: a fix applied to a parent branch *after* a child was cut lives only in staging (via the parent's squash) — when cascading the child, take `--theirs` for that file (or re-apply the fix) so you don't drop it. See [[feedback_squash_stack_cascade]].
