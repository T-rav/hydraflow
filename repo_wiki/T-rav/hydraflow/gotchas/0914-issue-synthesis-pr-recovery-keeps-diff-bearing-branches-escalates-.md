---
id: 0914
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:15:44.768781+00:00
status: active
corroborations: 1
supersedes: 0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797,0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0826,0827,0828,0829,0830,0833,0834,0838,0839,0840,0841,0842,0843,0844,0848,0848,0848,0849,0850
---

# PR recovery keeps diff-bearing branches, escalates zero-diff to HITL

Amending `docs/adr/0005-pr-recovery-and-zero-diff-branch-handling.md`: a branch with commits and a real diff from base that fails to open a PR should recover (retry `gh pr create`, adopt an existing PR, or mark pending for re-pick) rather than parking. A branch with zero diff from base still escalates to HITL — there's nothing to salvage. Keep this distinction explicit in `_handle_no_pr_fallback`'s logic in `src/implement_phase.py`.

**Why:** treating all no-PR outcomes identically either strands salvageable pushed work or silently auto-recovers empty branches that need a human's attention.
