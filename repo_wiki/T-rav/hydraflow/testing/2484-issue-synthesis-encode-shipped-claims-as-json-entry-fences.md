---
id: 2484
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:50.226710+00:00
status: active
corroborations: 1
supersedes: 2294
---

# Encode shipped claims as json:entry fences

When a synthesis entry must assert a `fixed_in_pr`/`code_refs` claim, render it as a `json:entry` machine block in the body rather than inventing a new frontmatter format. `wiki_rot_citations.extract_shipped_claims` already reads exactly that shape, so `wiki_compiler.compile_topic_tracked` gets rot-detector coverage for free.

**Why:** A second, bespoke claim format would fork the reader that `wiki_rot_citations.py` and the tracked-root scan both depend on.
