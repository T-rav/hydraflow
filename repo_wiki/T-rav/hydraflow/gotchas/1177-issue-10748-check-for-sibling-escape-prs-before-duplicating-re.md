---
id: 1177
topic: gotchas
source_issue: 10748
source_phase: plan
created_at: 2026-07-27T22:35:59.585802+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Check for sibling escape PRs before duplicating renderer changes

Before implementing an escape-resolution renderer fix, run `gh pr list --search escape-resolve` to check whether a sibling issue sharing the same escape hash already has a fix in flight.

- #10747 and #10748 both root-caused to escape `hotfix:4702cf9ddcd8`.
- If the sibling fix lands first, rebase and keep only the issue-specific ledger pin — do not duplicate the renderer change.

**Why:** Duplicate renderer edits from sibling issues cause merge conflicts and can regress the byte-identical aging-body contract.
