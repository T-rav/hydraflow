---
id: 0173
topic: architecture
source_issue: 10420
source_phase: plan
created_at: 2026-07-24T06:29:23.521334+00:00
status: active
corroborations: 1
---

# Fan-out citation counting excludes Superseded/Deprecated ADRs and :Symbol citations

When computing fan-out for `derive_shared_infra` in `src/adr_drift.py`, citations from ADRs with status Superseded or Deprecated, and citations scoped to a specific symbol (`path:Symbol` form), must not count toward the `min_fanout` threshold — only bare `src/` module citations from live ADRs count.

**Why:** counting stale or overly-specific citations would inflate fan-out and trigger suppression for modules that aren't actually broadly load-bearing across current architecture.
