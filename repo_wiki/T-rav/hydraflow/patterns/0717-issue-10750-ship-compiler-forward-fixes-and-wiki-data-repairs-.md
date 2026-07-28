---
id: 0717
topic: patterns
source_issue: 10750
source_phase: plan
created_at: 2026-07-27T22:53:53.519950+00:00
status: active
corroborations: 1
---

# Ship compiler forward fixes and wiki data repairs in the same PR

When repairing wiki supersession frontmatter, the forward compiler fix must land in the same PR as the data repair. Example: P2 (`_resolve_supersession_ids` fix) and P4 (entry 1148/1154 repair) are coupled — repairing frontmatter without the compiler fix re-corrupts it next compile round. **Why:** Data-only repairs get re-corrupted next cycle, replaying the #10566 lesson.
