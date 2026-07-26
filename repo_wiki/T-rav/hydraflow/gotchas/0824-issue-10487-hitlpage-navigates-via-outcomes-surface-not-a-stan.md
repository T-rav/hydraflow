---
id: 0824
topic: gotchas
source_issue: 10487
source_phase: plan
created_at: 2026-07-24T22:26:43.556491+00:00
status: superseded
corroborations: 1
superseded_by: 0851
---

# HitlPage navigates via Outcomes surface, not a standalone HITL tab

`tests/scenarios/browser/pages/hitl.py`'s `HitlPage.open()` used to click a dedicated "HITL" tab; that tab was removed when HITL merged into the Outcomes surface, and `/?tab=hitl` now lands on Outcomes instead of erroring. Locators for HITL rows/detail/textarea/skip stay `data-testid`-based and unchanged — only the entry navigation and docstrings (here and in `tests/scenarios/browser/workflows/test_hitl_roundtrip.py`) needed updating.
**Why:** stale UI-surface assumptions in page objects cause navigation timeouts that look like app bugs but are just test drift after a UI merge.
