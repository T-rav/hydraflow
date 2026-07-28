---
id: 0069
topic: architecture
source_issue: 6337
source_phase: plan
created_at: 2026-04-10T05:49:11.253590+00:00
status: stale
stale_reason: no repo-specific anchor (generic best-practice)
---

# f-string output decoupled from parameter naming

Directory path format `issue-{N}` comes from f-string template, not the parameter name. Renaming the parameter doesn't affect directory structure, making the rename purely cosmetic at the output level.
