---
id: 0219
topic: architecture
source_issue: 10585
source_phase: plan
created_at: 2026-07-26T02:30:26.057552+00:00
status: active
corroborations: 1
---

# FakeGitHub needs an explicit failure seam to test fail-soft ports

MockWorld's `FakeGitHub` (src/mockworld/fakes/fake_github.py) only models happy-path `create_issue`, so fail-soft retry logic (e.g. in `EscapeLedgerLoop`) can't be scenario-tested without adding a seam. Pattern: add `fail_next_create_issue(count: int = 1)`, mirroring the existing `seed_*`/`set_*` seeding style — next N calls return `0` and record no issue, then normal behavior resumes. Default inactive so existing scenarios are unaffected.
**Why:** without an injectable failure mode, fail-soft contract paths (like the one exploited in escape-ledger issue #10585) stay untested at the scenario layer even after the unit-level fix lands.
