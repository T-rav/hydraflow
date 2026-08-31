---
id: 2781
topic: testing
source_issue: 11547
source_phase: plan
created_at: 2026-08-30T07:44:19.983878+00:00
status: active
corroborations: 1
---

# Refresh mass.yaml via regen_mass_baseline --only, never blanket

When updating `disturbance/baselines/mass.yaml` after a burn-down bite, always run `regen_mass_baseline.py --only src/config.py --only src/config.py:HydraFlowConfig --reason "..."`. Never blanket-regen.
- Verify with `pytest tests/architecture/test_mass_ratchet.py` before and after refresh
- Every unchanged line in the baseline must stay byte-identical
**Why:** A blanket regen launders unrelated mass growth into the PR, defeating the ratchet that catches new god files and god classes.
