---
id: 0899
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:15:44.751869+00:00
status: superseded
corroborations: 1
supersedes: 0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797,0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0826,0827,0828,0829,0830,0833,0834,0838,0839,0840,0841,0842,0843,0844,0848,0848,0848,0849,0850
superseded_by: 0940
---

# ADR citation regex is `.py`-only; `.js::` cites are inert, not bugs

`adr_index._SOURCE_FILE_CITATION_RE` only matches `.py` source paths, so a malformed cite like `constants.js::…` (as seen on ADR-0049 line 76) is simply ignored rather than mis-parsed — it's dead weight in the doc, not a drift-gate blind spot, and doesn't need fixing alongside `.py::` repoints.

Example: when repointing double-colon citations, only touch `.py::` spans; leave non-Python extension citations as-is.

**Why:** Avoids scope creep on doc-fix PRs — conflating inert `.js` cites with the load-bearing `.py::` bug wastes review cycles on a non-issue.
