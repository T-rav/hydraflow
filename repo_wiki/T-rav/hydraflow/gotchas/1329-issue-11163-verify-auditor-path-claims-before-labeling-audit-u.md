---
id: 1329
topic: gotchas
source_issue: 11163
source_phase: plan
created_at: 2026-08-14T18:57:58.285631+00:00
status: active
corroborations: 1
---

# Verify auditor path claims before labeling audit-upheld

Auditor claims about which code path gates on which reader must be verified against source before acting. In #11163 the auditor asserted `_reconcile_surfaced_issues` gates on `terminal_ids()`; it actually uses `dismissal_reasons()`, which was already diagnosis-aware and unaffected.

Label `audit-upheld` only for the selection path actually verified (`_surface_findings` exclusion). Do not blanket-apply the label.

**Why:** Acting on unverified auditor claims risks mutating unaffected code paths and breaking unrelated regression pins (#11148 HITL closes).
