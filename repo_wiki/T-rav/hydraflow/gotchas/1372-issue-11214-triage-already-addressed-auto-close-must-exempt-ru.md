---
id: 1372
topic: gotchas
source_issue: 11214
source_phase: plan
created_at: 2026-08-15T05:26:51.324046+00:00
status: active
corroborations: 1
---

# Triage already_addressed auto-close must exempt runtime alert labels

`already_addressed` auto-close in `src/triage_phase.py` must skip runtime alert labels like `factory-stale-code`. Normal issues flagged already-addressed are still closed and commented.

- `factory-stale-code` + already-addressed → not auto-closed.
- Normal issue + already-addressed → closed + commented.

**Why:** Runtime alerts represent live system state, not fixable work items; auto-closing suppresses the signal `_check_stale_code` needs to re-arm the dead-man-switch.
