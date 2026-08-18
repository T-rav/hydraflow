---
id: 1493
topic: gotchas
source_issue: 11423
source_phase: plan
created_at: 2026-08-18T04:02:35.358180+00:00
status: active
corroborations: 1
---

# Fakes must mirror Port parameter kinds, not just names

Every Fake method's parameter `Parameter.kind` must match its Port counterpart exactly — a positional-or-keyword Port param cannot become keyword-only in the Fake.

- `FakeGitHub.list_closed_issues_by_label` had `*,` before `limit`, while `PRPort` (`src/ports.py:497`) and `PRManager` (`src/pr_manager.py:1234`) declared it positional-or-keyword.
- Fix: remove the `*,` separator; do not change the body.

**Why:** A call shape the Port permits (e.g. `list_closed_issues_by_label("label", 2)`) raises `TypeError` only under MockWorld, so the mismatch is invisible in production but breaks test fidelity.
