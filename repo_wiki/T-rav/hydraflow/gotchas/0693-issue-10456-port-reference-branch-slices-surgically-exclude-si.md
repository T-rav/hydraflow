---
id: 0693
topic: gotchas
source_issue: 10456
source_phase: plan
created_at: 2026-07-24T12:31:36.987755+00:00
status: superseded
corroborations: 1
superseded_by: 0704
---

# Port reference-branch slices surgically — exclude sibling-child scope

When porting proven logic from a reference branch (e.g. `agent/issue-10411`) into a new issue's PR, pull only the commits/files relevant to the current issue and explicitly exclude sibling-child changes bundled in the same branch. For issue #10456, that meant taking the `_bare_citation_fanout` / `_citation_drifts` slice from commit 92c9a12c but explicitly NOT touching `src/state/_adr_audit.py`'s `adr_numbers` changes, which belong to a separate fleet-triage child issue.

**Why:** pulling in sibling-child changes causes scope bleed and merge conflicts when that sibling child lands its own PR later — the issue's reference-branch pointer is a locator for the right commit, not license to port the whole branch.
