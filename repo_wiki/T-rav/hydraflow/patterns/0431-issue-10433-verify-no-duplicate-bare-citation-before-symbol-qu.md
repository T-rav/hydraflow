---
id: 0431
topic: patterns
source_issue: 10433
source_phase: plan
created_at: 2026-07-24T10:22:54.781348+00:00
status: superseded
corroborations: 1
superseded_by: 0432
---

# Verify no duplicate bare citation before symbol-qualifying an ADR line

Before narrowing a citation from bare `src/foo.py` to `src/foo.py:Class.method`, grep the whole ADR file for other bare citations of the same path — `adr_index.py:249`'s bare-collapse rule means a second bare occurrence anywhere in the doc reverts the fix by re-widening the symbol set. Confirm the target line is the *only* path-citation of that file before editing (done for ADR-0019 line 121 in #10433).

**Why:** a missed duplicate bare citation silently undoes the drift fix and the rollup re-fires on the next unrelated touch.
