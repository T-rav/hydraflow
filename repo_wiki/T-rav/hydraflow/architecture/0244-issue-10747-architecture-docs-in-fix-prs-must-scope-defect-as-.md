---
id: 0244
topic: architecture
source_issue: 10747
source_phase: review
created_at: 2026-07-27T23:55:24.611762+00:00
status: stale
corroborations: 1
stale_reason: source issue #10747 closed
---

# Architecture docs in fix-PRs must scope defect as historical

When an architecture doc ships in the same PR that fixes a defect it describes, write the defect narrative as historical, not current.

Example: `docs/architecture/escape-resolution.likec4` described the low-confidence `--encoded-as` defect in present tense ("DEFECT SITE", "current, defective") while the fix was in the same PR — stale on arrival. Reword component descriptions and dynamic view labels to describe the post-fix system as current and scope defects as "HISTORICAL — fixed by #10747, no longer current."

**Why:** Present-tense defect descriptions in a merged fix-PR mislead future readers into believing the defect still exists, violating the self-documenting-architecture discipline (see wiki: "Wiki entries can assert unbuilt mechanisms").
