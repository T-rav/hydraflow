---
id: 0911
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:15:44.765413+00:00
status: active
corroborations: 1
supersedes: 0764,0765,0766,0767,0768,0769,0770,0771,0772,0773,0774,0775,0776,0777,0778,0779,0780,0781,0782,0783,0784,0785,0786,0787,0788,0789,0790,0791,0792,0793,0794,0795,0796,0797,0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0826,0827,0828,0829,0830,0833,0834,0838,0839,0840,0841,0842,0843,0844,0848,0848,0848,0849,0850
---

# HitlPage navigates via Outcomes surface, not a standalone HITL tab

`tests/scenarios/browser/pages/hitl.py`'s `HitlPage.open()` used to click a dedicated "HITL" tab; that tab was removed when HITL merged into the Outcomes surface, and `/?tab=hitl` now lands on Outcomes instead of erroring. Locators for HITL rows/detail/textarea/skip stay `data-testid`-based and unchanged — only the entry navigation and docstrings (here and in `tests/scenarios/browser/workflows/test_hitl_roundtrip.py`) needed updating.

**Why:** stale UI-surface assumptions in page objects cause navigation timeouts that look like app bugs but are just test drift after a UI merge.
