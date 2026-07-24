---
id: 0166
topic: architecture
source_issue: 10400
source_phase: plan
created_at: 2026-07-24T05:41:19.861275+00:00
status: stale
corroborations: 1
stale_reason: source issue #10400 closed
---

# `_SHARED_INFRA_MODULES` exempts shared files from ADR drift regardless of citation form

Files listed in `_SHARED_INFRA_MODULES` (e.g. `post_merge_handler.py`, `models.py` as cited from ADR-0012) never drift no matter how they're cited, so bare citations to them don't need right-sizing. When fixing a drifting citation on one line of an ADR, leave adjacent shared-infra citations on other lines untouched — enlarging the diff to "fix" them is unnecessary and increases review surface for no behavior change.

**Why:** Confusing the shared-infra exemption with the symbol-qualification fix leads to needless diff churn on lines that were never actually at risk.
