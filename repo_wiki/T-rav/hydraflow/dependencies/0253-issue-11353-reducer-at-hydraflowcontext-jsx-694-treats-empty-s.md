---
id: 0253
topic: dependencies
source_issue: 11353
source_phase: plan
created_at: 2026-08-16T14:57:57.978716+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Reducer at HydraFlowContext.jsx:694 treats empty stage arrays as authoritative

The pipeline reducer (`HydraFlowContext.jsx:694`) treats a `/api/pipeline` reply where every stage key → `[]` as authoritative truth, not as a transient boot-window state. A boot-window empty reply is byte-indistinguishable from a genuinely empty pipeline, so the rail renders zero cards even when labels are non-empty.

**Why:** Identifies the root cause of the 2026-08-15 operator repro — the reducer lacks a guard distinguishing 'empty because restarting' from 'empty because nothing exists'.
