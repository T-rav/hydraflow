---
id: 0721
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T15:44:15.979627+00:00
status: active
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
---

# Put WS-broadcast fields on both the summary and detail model, not detail-only

If a field is only added to a detail-only model (e.g. `EpicDetail`), but the live update path (`epic_update` reducer) replaces panel state with the summary model (`EpicProgress`), the field will flap to its default on every WS push.

Example: for issue #10299's `execution` field on `src/models.py`, it had to be added to BOTH `EpicProgress` and `EpicDetail` for this reason.

**Why:** Reducers that swap in a narrower payload silently erase fields the wider payload had, causing UI flicker that's hard to reproduce outside a live WS session.
