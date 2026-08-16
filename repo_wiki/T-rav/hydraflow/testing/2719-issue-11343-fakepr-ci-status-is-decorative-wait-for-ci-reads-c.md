---
id: 2719
topic: testing
source_issue: 11343
source_phase: plan
created_at: 2026-08-16T13:08:39.701148+00:00
status: active
corroborations: 1
---

# FakePR.ci_status is decorative; wait_for_ci reads _ci_scripts

Setting `ci_status: "fail"` on a seeded `FakePR` does not drive the CI-fix leg. `wait_for_ci` (`fake_github.py:830`) reads `_ci_scripts` and never inspects `FakePR.ci_status`, so the `fix_ci` script is never popped.

- Seeded CI failure state is purely cosmetic in sandbox scenarios
- Document this limitation in scenario docstrings rather than removing the `fix_ci` entry
- File a separate follow-up to wire `ci_status` into `wait_for_ci`

**Why:** Tests that appear to exercise red-CI-to-green transitions pass for the wrong reason — the fix leg never fires, so the assertion validates nothing about CI recovery.
