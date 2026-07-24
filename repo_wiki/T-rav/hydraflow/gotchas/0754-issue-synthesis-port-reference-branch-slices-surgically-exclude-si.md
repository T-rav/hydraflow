---
id: 0754
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:18:53.914616+00:00
status: active
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
---

# Port reference-branch slices surgically — exclude sibling-child scope

When porting proven logic from a reference branch (e.g. `agent/issue-10411`) into a new issue's PR, pull only the commits/files relevant to the current issue and explicitly exclude sibling-child changes bundled in the same branch.

Example: for issue #10456, that meant taking the `_bare_citation_fanout` / `_citation_drifts` slice from commit 92c9a12c but explicitly NOT touching `src/state/_adr_audit.py`'s `adr_numbers` changes, which belong to a separate fleet-triage child issue.

**Why:** Pulling in sibling-child changes causes scope bleed and merge conflicts when that sibling child lands its own PR later — the issue's reference-branch pointer is a locator for the right commit, not license to port the whole branch.
