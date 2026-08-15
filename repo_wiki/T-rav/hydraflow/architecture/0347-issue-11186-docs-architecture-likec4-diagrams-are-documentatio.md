---
id: 0347
topic: architecture
source_issue: 11186
source_phase: review
created_at: 2026-08-15T02:28:30.947521+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# docs/architecture/*.likec4 diagrams are documentation-only

Adding `.likec4` files under `docs/architecture/` follows an established repo convention (56 existing hand-authored diagrams). These files are not wired into CI or build tooling — they are purely documentation.

**Why:** Treating new `.likec4` additions as scope creep misreads the repo's documentation practices; they match an unenforced convention and require no tooling integration.
