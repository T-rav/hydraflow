---
id: 0901
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:15:44.754103+00:00
status: active
corroborations: 1
supersedes: 0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797,0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0826,0827,0828,0829,0830,0833,0834,0838,0839,0840,0841,0842,0843,0844,0848,0848,0848,0849,0850
---

# Port reference-branch slices surgically — exclude sibling-child scope

When porting proven logic from a reference branch (e.g. `agent/issue-10411`) into a new issue's PR, pull only the commits/files relevant to the current issue and explicitly exclude sibling-child changes bundled in the same branch.

Example: for issue #10456, that meant taking the `_bare_citation_fanout` / `_citation_drifts` slice from commit 92c9a12c but explicitly NOT touching `src/state/_adr_audit.py`'s `adr_numbers` changes, which belong to a separate fleet-triage child issue.

**Why:** Pulling in sibling-child changes causes scope bleed and merge conflicts when that sibling child lands its own PR later — the issue's reference-branch pointer is a locator for the right commit, not license to port the whole branch.
