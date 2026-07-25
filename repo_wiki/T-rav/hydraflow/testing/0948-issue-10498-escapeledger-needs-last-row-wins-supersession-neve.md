---
id: 0948
topic: testing
source_issue: 10498
source_phase: plan
created_at: 2026-07-25T01:51:29.166471+00:00
status: superseded
corroborations: 3
superseded_by: 0954
---

# EscapeLedger needs last-row-wins supersession, never in-place rewrites

`EscapeLedger` (`src/escape/ledger.py`) is append-only. Reaching a terminal state (e.g. `encoded_as: detector` + `regression-test`) means appending a new row for the same id, never rewriting the original line.

- Derived readers must collapse to the latest row per id: `src/escape/metrics.py` and `src/escape_ledger_loop.py`'s `_render_reports`/`_surface_findings` all need the same latest-per-id read.
- `existing_ids()` must still contain the id exactly once after supersession, so a re-tick doesn't re-record.
- Keep the change to one read helper + one append helper — a growing mutation API is scope creep.

**Why:** the ledger's append-only guarantee preserves audit-trail integrity; in-place rewrites would erase false-positive history.
