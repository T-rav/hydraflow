---
id: 1156
topic: gotchas
source_issue: 10655
source_phase: plan
created_at: 2026-07-26T16:28:39.816255+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Key wiki corpus by (topic, id), not id alone

Wiki entry IDs are unique per topic dir only. `gotchas/0001` and `dependencies/0001` are distinct entries. When building a corpus index via `wiki_supersession_repair.load_topic_entries` + `discover_topics`, key entries by the `(topic, id)` tuple.
- Keying by id alone silently cross-links topics and corrupts coverage analysis.
**Why:** An id collision across topic dirs causes an auditor to report a predecessor as "represented" when its content lives in a different topic's entry.
