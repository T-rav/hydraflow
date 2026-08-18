---
id: 0406
topic: architecture
source_issue: 11412
source_phase: review
created_at: 2026-08-18T08:06:05.370495+00:00
status: active
corroborations: 1
---

# docs/architecture/*.likec4 are planner-injected scratch, not deliverables

`.likec4` files under `docs/architecture/` are planner-injected worktree scratch, not curated deliverables — `src/null_delivery.py`'s `is_non_deliverable_path` classifies them as non-deliverable.

- Delete stale `.likec4` diagrams that assert defects already fixed by ancestor commits, rather than leaving false claims that audit tooling reads as ground truth.
- Do not treat their presence in a PR diff as a deliberate scope addition requiring plan amendment.

**Why:** Git-tracked architecture diagrams with stale defect claims become false provenance for the repo's own audit tooling (SampledAuditLoop, escape-ledger) that reads tracked files as substrate.
