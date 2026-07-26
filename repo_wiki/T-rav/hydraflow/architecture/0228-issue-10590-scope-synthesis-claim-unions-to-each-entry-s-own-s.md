---
id: 0228
topic: architecture
source_issue: 10590
source_phase: plan
created_at: 2026-07-26T04:12:39.569036+00:00
status: active
corroborations: 1
---

# Scope synthesis claim unions to each entry's own `supersedes` list, not a global blob

In `wiki_compiler.compile_topic_tracked`, when unioning claims onto a synthesis entry, key the union off the ids in *that entry's own* `supersedes` list rather than pooling every claim in the topic. This makes the design self-correcting: if #10566 later makes synthesis 1:1, the mapping narrows automatically with no code change. Global pooling while supersedes is still N:M would duplicate claims across sibling synthesis files and inflate rot-detector findings.
**Why:** avoids a second migration when #10566 lands, and prevents duplicate claims from multiplying false rot findings today.
