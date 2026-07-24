---
id: 0763
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T22:06:52.501750+00:00
status: active
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
---

# Clear hitl-escalation label only alongside diagnose-failed

In `escalated_with_resolving_pr` (src/pr_manager.py), require BOTH `hitl-escalation` AND `diagnose-failed` labels before clearing `hydraflow-hitl-escalation` — don't rely on bare set-intersection truthiness.

Example: `corpus_learning_loop.py`, `trust_fleet_sanity_loop.py`, and `wiki_rot_detector_loop.py` file bare `hitl-escalation` plus their own `-stuck` label with no pipeline label backing it, and won't re-file until an operator closes the issue.

**Why:** Clearing escalation unconditionally trades a retry-storm bug for a silent-deadlock bug in every non-`diagnostic_loop` lineage, since those issues would never get requeued.
