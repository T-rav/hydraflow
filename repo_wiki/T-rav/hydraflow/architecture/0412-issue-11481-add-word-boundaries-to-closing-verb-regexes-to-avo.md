---
id: 0412
topic: architecture
source_issue: 11481
source_phase: plan
created_at: 2026-08-20T09:13:45.273109+00:00
status: active
corroborations: 1
---

# Add word boundaries to closing-verb regexes to avoid false matches

Always use `CLOSE_KEYWORD_RE` from `src/false_close.py` instead of manually compiling patterns like `(?:fixes|closes|resolves)\s+#(\d+)`. The canonical pattern includes `\b` boundaries.

**Why:** Local patterns without boundaries match substrings like `prefixes #99`, causing silent false positives in issue resolvers.
