---
id: 1237
topic: gotchas
source_issue: 10904
source_phase: plan
created_at: 2026-07-31T10:40:34.520348+00:00
status: active
corroborations: 1
---

# Guard-test duplicated CI path lists instead of unifying

When CI lanes consume *different derivations* of one path set, keep the duplication and make drift fail red — don't unify. Precedent: `tests/regressions/test_issue_10049_linux_signal_lane.py` uses `yaml.safe_load` + bidirectional set equality + paths-exist. New guard `tests/regressions/test_issue_10904_serial_path_sync.py` applies the same pattern to `REAP_TESTS` / `PYTEST_SERIAL_PATHS` / `xdist-audit.yml` ignores.

**Why:** Unifying disparate concepts (e.g. `REAP_TESTS` vs `subprocess_signal`'s 6-file set, #9922) widens a deliberately non-gating advisory lane.
