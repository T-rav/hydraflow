---
id: 1551
topic: gotchas
source_issue: 11937
source_phase: plan
created_at: 2026-09-01T09:28:20.470723+00:00
status: active
corroborations: 1
---

# Regression triple-pin: visibility + non-redden counter + FAIL liveness

Pin advisory restorations with three tests in `tests/regressions/test_issue_*.py`: (a) advisory reason reaches `format_terminal` output — RED before fix; (b) same findings keep `overall_exit_code == 0` — catches WARN-restored-without-the-non-blocking-set; (c) blocking FAIL message still renders — liveness against overzealous suppression.

See `tests/regressions/test_issue_11937.py` for the pattern.

**Why:** Visibility alone doesn't catch a WARN that reddens the gate; liveness catches silent FAIL suppression.
