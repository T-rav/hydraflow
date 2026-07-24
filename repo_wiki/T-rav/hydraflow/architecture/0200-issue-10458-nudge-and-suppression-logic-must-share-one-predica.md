---
id: 0200
topic: architecture
source_issue: 10458
source_phase: plan
created_at: 2026-07-24T13:01:26.369125+00:00
status: active
corroborations: 1
---

# Nudge and suppression logic must share one predicate in adr_drift.py

When adding a new pure-logic feature that mirrors an existing check (e.g. `bare_infra_citation_nudges` alongside `_citation_drifts`), extract the shared test into one predicate both call — don't reimplement the `_SHARED_INFRA_MODULES` membership check twice. If `_citation_drifts` and a nudge/report function diverge on what counts as shared infra, the nudge will fire on paths that don't actually drift-suppress (or vice versa), silently breaking the doc's usefulness. **Why:** two independent copies of a classification rule drift apart the first time one side is updated (e.g. when #10456's fanout-aware set lands) and nobody remembers to update both.
