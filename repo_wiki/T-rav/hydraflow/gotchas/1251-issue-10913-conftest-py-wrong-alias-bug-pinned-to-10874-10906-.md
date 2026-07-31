---
id: 1251
topic: gotchas
source_issue: 10913
source_phase: plan
created_at: 2026-07-31T13:38:55.527472+00:00
status: active
corroborations: 1
---

# conftest.py wrong-alias bug pinned to #10874/#10906 — don't fix incidentally

Rule: `tests/conftest.py` contains a wrong-alias import (`src.telemetry.spans`) that clears the wrong tracer cache. This is owned by #10874/#10906. Do not edit `tests/conftest.py` in unrelated PRs even if the bug masks a test failure.

Example: #10913's `FakeHoneycomb.__init__` construct-time invalidation partially masks #10883 without touching conftest — the masking is documented in the PR body, and #10906's static `src.`-prefix import guard remains the real pin.

**Why:** Editing conftest collides with in-flight work on #10874/#10906 and risks merge conflicts.
