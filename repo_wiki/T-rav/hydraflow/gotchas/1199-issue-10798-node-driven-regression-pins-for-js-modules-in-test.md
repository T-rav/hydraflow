---
id: 1199
topic: gotchas
source_issue: 10798
source_phase: plan
created_at: 2026-07-28T10:05:46.407754+00:00
status: active
corroborations: 1
---

# Node-driven regression pins for JS modules in `tests/regressions/`

Drive shipped JS (e.g. `src/ui/src/operator/model/vitals.js`) through `node` with an ESM resolve hook — `vitals.js` imports `./pipeline` extensionless. Follow `regression_issue_10556.py` docstring convention. Include:

- A control case (one input) proving the harness works independently of the fix.
- A discriminating case that fails red on pre-fix code.
- Guard with `pytest.mark.skipif(shutil.which("node") is None)` — skip, never xfail.

**Why:** Brittle module resolution or absent node in CI must not turn the pin red; the control test isolates harness failure from fix failure, and skip-not-fail keeps CI honest.
