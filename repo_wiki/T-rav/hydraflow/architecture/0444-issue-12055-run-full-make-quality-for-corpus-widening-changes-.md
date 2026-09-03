---
id: 0444
topic: architecture
source_issue: 12055
source_phase: plan
created_at: 2026-09-02T21:55:38.779847+00:00
status: active
corroborations: 1
---

# Run full `make quality` for corpus-widening changes, not targeted test subsets

When modifying a tree-wide check (corpus-widening, generalization), run the full test suite per CLAUDE.md cleanup-PR rule, not per-directory subsets.

Example: PR #8460 ran 211 tests in three targeted files (all green) but missed 7 failures in test_audit_prompts.py and test_repo_wiki_loop_pr.py; hotfix PR #8463 followed.

**Why:** Blast radius of tree-wide checks exceeds diff visibility; targeted subsets produce false confidence.
