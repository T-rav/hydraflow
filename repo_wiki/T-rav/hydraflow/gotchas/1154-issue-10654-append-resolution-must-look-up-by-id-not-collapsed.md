---
id: 1154
topic: gotchas
source_issue: 10654
source_phase: plan
created_at: 2026-07-26T16:24:44.376086+00:00
status: active
corroborations: 1
---

# append_resolution must look up by id, not collapsed view

`EscapeLedger.append_resolution()` must use `latest_by_id(self.read_all())`, never the `latest_by_escape`-collapsed `read_latest()`.

- The HITL body renders `make escape-resolve ARGS="<id> …"` (`escape_ledger_loop.py:647`) using the losing id.
- If `append_resolution` queried the collapsed view, that id would be absent and the call would return `None`, stranding already-filed issues.

**Why:** Resolution is keyed by id; collapsing away the losing row silently breaks `make escape-resolve` for every previously-filed HITL issue.
