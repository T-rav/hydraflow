---
id: 1498
topic: gotchas
source_issue: 11423
source_phase: review
created_at: 2026-08-18T05:56:04.201963+00:00
status: stale
corroborations: 1
stale_reason: source issue #11423 closed
---

# Verify RED baseline by reverting FakeGitHub before GREEN check

Before confirming a fix is GREEN, revert the fake to its pre-fix state and confirm the exact failure mode the issue describes.

For `FakeGitHub` in `fake_github.py`: revert → confirm 4/7 tests fail with the `TypeError` from the issue → re-apply fix → confirm 7/7 pass.

**Why:** Without a true RED baseline, GREEN tests may pass for the wrong reason or against a stale fake that never exercised the bug.
