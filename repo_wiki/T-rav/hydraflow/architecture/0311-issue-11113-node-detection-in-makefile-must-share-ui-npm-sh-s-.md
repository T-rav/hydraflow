---
id: 0311
topic: architecture
source_issue: 11113
source_phase: plan
created_at: 2026-08-14T09:30:40.585878+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Node detection in Makefile must share ui-npm.sh's resolution chain

Guard the UI test lane with `scripts/ui-npm.sh --can-run` instead of duplicating the current-PATH → nvm → fnm → volta → brew chain in the Makefile. The `UI_TEST_CMD` guard becomes `[ -d src/ui/node_modules ] && scripts/ui-npm.sh --can-run` (cheap dir test first); the run branch calls `scripts/ui-npm.sh test`.

**Why:** A second copy of the chain drifts from the run path and skips vitest on nvm-only shells — the exact #11113 bug.
