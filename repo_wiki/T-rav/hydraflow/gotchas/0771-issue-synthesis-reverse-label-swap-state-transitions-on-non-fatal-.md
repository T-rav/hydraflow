---
id: 0771
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:43:03.965574+00:00
status: active
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
---

# Reverse label-swap state transitions on non-fatal exceptions

Wrap label-swap + operation + cleanup in try/except and reverse the transition on non-fatal errors, per the ADR-0002 labels-as-state-machine model.

Example: if a label is swapped `plan → implement` but the follow-up API call fails, swap it back to `plan` before re-raising.

**Why:** An exception after a successful state transition but before cleanup leaves issues stuck in intermediate label states with no automated recovery path.
