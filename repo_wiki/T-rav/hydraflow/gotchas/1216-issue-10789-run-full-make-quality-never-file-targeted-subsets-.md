---
id: 1216
topic: gotchas
source_issue: 10789
source_phase: plan
created_at: 2026-07-31T02:16:58.506490+00:00
status: active
corroborations: 1
---

# Run full make quality, never file-targeted subsets after flag excision

Run full `make quality` before merging flag/config removals; never a file-targeted test subset. Read the vulture output line-by-line, not skimmed.

- PR #8460 precedent: targeted tests passed while `make quality` failed on a collaterally-orphaned symbol.
- P6 in issue #10789's plan is explicitly non-negotiable for this reason.

**Why:** Excising a flag cascades to symbols whose only consumers were the removed code; only full vulture + the complete quality suite catches these orphans.
