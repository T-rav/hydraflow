---
source: feedback_fresh_worktree_npm_ci_false_green.md
name: feedback_fresh_worktree_npm_ci_false_green
description: A fresh git worktree has no src/ui/node_modules, so `make quality` SILENTLY SKIPS the UI/vitest stage ([ui-tests SKIPPED]) and reports green — a FALSE green that hides broken UI. Always `npm ci` (or `npm install`) in src/ui before make quality in a new worktree doing UI work.
status: pending
issue: null
promoted_in: null
wontfix_reason: null
created: '2026-07-26'
---

**Trap (hit repeatedly during operator-console #10556 UI tasks):** `git worktree add` creates a worktree that does NOT share `src/ui/node_modules` with the main checkout. If you run `make quality` there without installing UI deps first, the UI/vitest lane **silently skips** (`[ui-tests SKIPPED]`) instead of failing — so `make quality` exits 0 and looks green while your React changes were never tested. That's a FALSE green that can merge broken UI (and CI *would* catch it, wasting a round-trip, or worse if CI also mis-skips).

**How to apply:**
- In any worktree doing `src/ui` work, run `npm ci` (preferred; respects `package-lock.json`) or `npm install` in `src/ui/` BEFORE `make quality`. Bake this into UI-task subagent prompts.
- Treat `[ui-tests SKIPPED]` in `make quality` output as a RED FLAG, not a pass — it means the UI lane didn't run. The authoritative vitest invocation is `node src/ui/scripts/run-vitest.cjs run` (the `run` subcommand; bare watch mode misreports mass failures because jsdom setup doesn't apply).
- `package-lock.json` is unchanged by `npm ci`, so this adds no diff.

Related: [[feedback_make_quality_green_neq_ci_green]] · [[feedback_subagent_backgrounds_quality_then_stops]] · [[feedback_make_quality_pipe_exit_code]] (PIPESTATUS is unreliable under zsh — capture `$?` directly).
