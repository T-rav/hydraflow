---
id: 0221
topic: architecture
source_issue: 10586
source_phase: plan
created_at: 2026-07-26T02:51:38.701781+00:00
status: active
corroborations: 1
---

# Aggregate wiki-rot tracked-scan skip logs, one WARNING per directory per tick

When `WikiRotDetectorLoop` or the `src/repo_wiki.py` tracked reader skips entries during a scan (non-`active` status, parse failure), log one aggregated WARNING per directory per tick with a literal format string — not a line per skipped entry.

**Why:** per-entry logging in the tracked reader already produced ~7.6k WARNING lines in a single run before this was caught.
