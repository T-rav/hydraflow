---
id: 0192
topic: architecture
source_issue: 10451
source_phase: plan
created_at: 2026-07-24T12:15:48.605872+00:00
status: active
corroborations: 1
---

# No CI validates .likec4 code references — grep-confirm before merging diagram PRs

LikeC4 files under `docs/architecture/` (e.g. `jsonl_ledger.likec4`) are not checked against `src/` by any pipeline. Before merging a diagram edit, grep every referenced class name and file path (e.g. `AppendOnlyJsonlLedger`, `IdentifiedJsonlLedger`, `src/erosion/trends.py`) against `src/` on the branch's merge base to catch dangling refs. Also run `git grep -niE "jsonlledger|trendstore" docs/wiki docs/adr` to check for stale wiki/ADR mentions before assuming an edit there is needed.
**Why:** review is the only gate for `.likec4` accuracy — an unverified rename or path typo ships silently and misleads the next reader of the diagram.
