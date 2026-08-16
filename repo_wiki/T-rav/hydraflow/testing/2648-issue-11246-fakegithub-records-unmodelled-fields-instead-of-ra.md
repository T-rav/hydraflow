---
id: 2648
topic: testing
source_issue: 11246
source_phase: plan
created_at: 2026-08-15T20:20:19.664569+00:00
status: active
corroborations: 1
---

# FakeGitHub records unmodelled fields instead of raising

When a `--json` selector field is not modelled by `FakeGitHub`, append it to a public recording list (e.g. `self.issue_view_unmodelled_fields`) and omit it from the payload — do not raise and do not fabricate.

This follows the fake's quiet-scenario philosophy: scenarios stay silent on drift. It complements #11237 strict mode, which catches unmatched flags but cannot catch matched-but-wrong shapes.

**Why:** Raising in the fake would break every MockWorld scenario that happens to pass an unmodelled flag; silent fabrication would hide shape drift from test authors.
