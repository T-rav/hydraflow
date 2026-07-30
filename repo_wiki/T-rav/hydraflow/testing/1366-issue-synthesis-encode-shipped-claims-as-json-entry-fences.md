---
id: 1366
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T22:47:42.367446+00:00
status: superseded
corroborations: 1
supersedes: 1292
superseded_by: 1441
---

# Encode shipped claims as json:entry fences

When a synthesis entry must assert a `fixed_in_pr`/`code_refs` claim, render it as a `json:entry` machine block in the body rather than inventing a new frontmatter format. `wiki_rot_citations.extract_shipped_claims` already reads exactly that shape, so `wiki_compiler.compile_topic_tracked` gets rot-detector coverage for free.

Example: the tracked frontmatter parser is a naive `key: value` split — it can't hold a `code_refs` list cleanly, so frontmatter-only encoding would silently lose data.

**Why:** A second, bespoke claim format would fork the reader that `wiki_rot_citations.py` and the tracked-root scan both depend on.
