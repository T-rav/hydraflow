---
id: 0155
topic: architecture
source_issue: 10304
source_phase: plan
created_at: 2026-07-24T03:55:27.919539+00:00
status: active
corroborations: 1
---

# AdrTouchpointAuditorLoop flags ADR text that drifts from cited src/ behavior

When code cited by an ADR changes behavior, the ADR text itself can silently go stale — e.g. `src/triage_phase.py` split its park terminal into clarification-park (24h, author input) and infra-park (`triage_infra_parked`, short retry, no HITL) via PR #10300/#10290, but ADR-0107's Routing section still said parking was "pending author input — unchanged." `AdrTouchpointAuditorLoop` detects this drift and files a rollup issue (e.g. #10304); merging the ADR fix lets its next tick auto-close the rollup.

**Why:** ADRs cited against a `src/*.py` file are load-bearing docs, not snapshots — code changes without a matching ADR amendment produce silent architectural drift that only the auditor loop catches.
