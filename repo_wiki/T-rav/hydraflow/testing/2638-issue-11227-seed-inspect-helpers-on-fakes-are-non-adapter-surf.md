---
id: 2638
topic: testing
source_issue: 11227
source_phase: plan
created_at: 2026-08-15T06:51:55.204475+00:00
status: active
corroborations: 1
---

# Seed/inspect helpers on fakes are non-adapter surface, no PRPort method needed

Methods like `seed_branch`, `branch_tip`, `branch_tips` on `FakeGitHub` are test scaffolding, not adapter surface. Do not mirror them on `PRPort`.

**Why:** `FakeCoverageAuditorLoop` classifies seed/inspect helpers as non-adapter surface. Adding them to `PRPort` would incorrectly flag real adapters as incomplete and couples the port to test-only concerns.
