---
id: 1150
topic: testing
source_issue: 10590
source_phase: plan
created_at: 2026-07-26T04:12:39.568995+00:00
status: superseded
corroborations: 1
superseded_by: 1218
---

# Encode shipped claims as json:entry fences — extract_shipped_claims already parses them

When a synthesis entry must assert a `fixed_in_pr`/`code_refs` claim, render it as a `json:entry` machine block in the body rather than inventing a new frontmatter format. `wiki_rot_citations.extract_shipped_claims` already reads exactly that shape, so `wiki_compiler.compile_topic_tracked` gets rot-detector coverage for free and #10586's tracked-root scan picks it up too. The tracked frontmatter parser is a naive `key: value` split — it can't hold a `code_refs` list cleanly, so frontmatter-only encoding would silently lose data.
**Why:** a second, bespoke claim format would fork the reader that `wiki_rot_citations.py` and the tracked-root scan both depend on.
