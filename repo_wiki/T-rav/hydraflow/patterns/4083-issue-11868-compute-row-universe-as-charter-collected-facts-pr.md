---
id: 4083
topic: patterns
source_issue: 11868
source_phase: plan
created_at: 2026-09-01T03:50:35.471720+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Compute row universe as charter ∪ collected ∪ facts-present

Rule: The row universe for standards-decisions rendering is `charter.articles.standards ∪ policy.COLLECTED_STANDARDS ∪ standards present in facts`. The charter drives a Declared column and the GAP universe.

- Do not add standard ids to `charter.yaml` — that is an operator ENACT action
- A charter-declared standard with zero decisions shows as a `gap` row, not silence
- Undeclared-but-collected standards still render with `Declared = no`

**Why:** Silence on declared-but-undecided standards makes conformance gaps invisible to readers.
