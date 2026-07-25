---
id: 0936
topic: gotchas
source_issue: 10565
source_phase: plan
created_at: 2026-07-25T23:03:04.264298+00:00
status: active
corroborations: 1
---

# tests/test_adr_drift.py's _adr_with_symbols hardcodes status="Accepted"

The test helper `_adr_with_symbols` in `tests/test_adr_drift.py` hardcodes `status="Accepted"` with no parameter to vary it — this is why the non-live nudge bug (issue #10565) shipped green: no test could construct a Superseded/Deprecated ADR fixture. When adding status-sensitive logic to `adr_drift.py`, first check whether this helper needs a `status` parameter before assuming existing tests cover the case.

**Why:** a fixture that can't represent non-default states makes an entire bug class untestable, even with high test count.
