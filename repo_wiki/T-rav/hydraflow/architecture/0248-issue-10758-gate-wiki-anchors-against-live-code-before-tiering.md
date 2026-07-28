---
id: 0248
topic: architecture
source_issue: 10758
source_phase: plan
created_at: 2026-07-27T23:48:31.703703+00:00
status: active
corroborations: 1
---

# Gate wiki anchors against live code before tiering coverage

Before asking whether any active wiki entry cites a predecessor's anchors, drop anchors whose symbol no longer resolves in live code. Suppress them into a `not_live` bucket, reported as a count, never silently dropped.

- Without this gate ~156/356 `left_on_primary` predecessors falsely read as zero-representation.
- `extract_cites(body)` + `code_refs` frontmatter anchors are checked against `module_symbols` output.

**Why:** Stale anchors create false orphans that drown the real signal — entries whose content genuinely left the corpus.
