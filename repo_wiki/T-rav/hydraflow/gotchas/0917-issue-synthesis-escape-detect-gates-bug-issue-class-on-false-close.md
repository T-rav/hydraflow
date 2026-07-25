---
id: 0917
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:15:44.772212+00:00
status: active
corroborations: 1
supersedes: 0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797,0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0826,0827,0828,0829,0830,0833,0834,0838,0839,0840,0841,0842,0843,0844,0848,0848,0848,0849,0850
---

# escape.detect gates bug-issue class on false_close.has_skip_regression

Gate only the `bug-issue` branch of `_classify` in `src/escape/detect.py` on the repo's existing `false_close.has_skip_regression` helper. A commit whose body carries `Skip-Regression:` declares itself behaviour-neutral, so it must not be recorded as a post-merge escape.

- Import the public helper (no leading underscore, per gotchas) rather than copying its regex — it's already the shared P10.6/P10.7 signature and stays pure/git-free.
- Apply the gate only to `bug-issue`: reverts and hotfixes carrying the same trailer must still be recorded as escapes, or the opt-out silences real defects.

**Why:** an over-broad gate above the precedence chain silences real reverts/hotfixes; a copied regex risks drifting from the canonical one.
