---
id: 2717
topic: testing
source_issue: 11338
source_phase: plan
created_at: 2026-08-16T12:34:38.645165+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Scenario seed prs=[] entries are a separate defect class from scripts[]

In scenario seed files, `scripts["implement"]` payloads and `prs=[{"branch": ...}]` entries look like the same branch-canonicalization defect but carry different behavior risk. Canonicalizing a seeded PR branch (e.g., `s04`'s `prs=[]`) makes `_flow_decompose`'s `find_open_pr_for_branch` shortcut fire and skip implement entirely — silently changing what the scenario tests.

Fix `scripts["implement"]` branches first; file `prs=[]` entries separately.

**Why:** Touching `prs=[]` entries alters scenario control flow, not just data, producing green tests that no longer exercise the intended path.
