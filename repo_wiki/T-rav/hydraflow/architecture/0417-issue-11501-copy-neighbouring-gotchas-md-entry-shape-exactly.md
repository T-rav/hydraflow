---
id: 0417
topic: architecture
source_issue: 11501
source_phase: plan
created_at: 2026-08-21T01:19:24.541907+00:00
status: active
corroborations: 1
---

# Copy neighbouring gotchas.md entry shape exactly

When adding a `##` entry to `docs/wiki/gotchas.md`, match the existing entry's structure byte-for-byte: prose block followed by a `json:entry` block in the same field order and indentation.

- Do not invent a new format or omit the `json:entry` block.
- The wiki tooling machine-parses these entries.

**Why:** A shape that drifts from the established format causes the wiki parser to silently drop or misclassify the entry, making the gotcha invisible to downstream tooling.
