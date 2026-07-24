---
id: 0813
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T23:38:39.537440+00:00
status: active
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
---

# Port reference-branch slices surgically — exclude sibling-child scope

When porting proven logic from a reference branch (e.g. `agent/issue-10411`) into a new issue's PR, pull only the commits/files relevant to the current issue and explicitly exclude sibling-child changes bundled in the same branch.

Example: for issue #10456, that meant taking the `_bare_citation_fanout` / `_citation_drifts` slice from commit 92c9a12c but explicitly NOT touching `src/state/_adr_audit.py`'s `adr_numbers` changes, which belong to a separate fleet-triage child issue.

**Why:** Pulling in sibling-child changes causes scope bleed and merge conflicts when that sibling child lands its own PR later — the issue's reference-branch pointer is a locator for the right commit, not license to port the whole branch.
