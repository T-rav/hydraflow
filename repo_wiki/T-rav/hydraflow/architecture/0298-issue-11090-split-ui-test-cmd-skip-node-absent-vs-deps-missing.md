---
id: 0298
topic: architecture
source_issue: 11090
source_phase: plan
created_at: 2026-08-14T06:25:31.261762+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Split UI_TEST_CMD skip: node-absent vs deps-missing

Distinguish "can't run vitest here" from "one `npm ci` away" in `UI_TEST_CMD` (Makefile:492). Node absent on PATH → print `[ui-tests SKIPPED]`, exit 0. Node present but `src/ui/node_modules` absent → print `[ui-tests BLOCKED]`, exit 1, name `make ui-deps`.

**Why:** Collapsing both into one skip branch (#9875's deliberate degrade) lets a fresh worktree with node installed report a false green, hiding a trivially fixable gap.
