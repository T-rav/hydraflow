---
id: 1215
topic: gotchas
source_issue: 10860
source_phase: plan
created_at: 2026-07-31T01:48:16.698181+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Same-builder fixture targets must each cover a unique statement

When multiple registry targets share a `builder_qualname`, enforce that each covers at least one statement no sibling covers. The ratchet fails, naming both targets, if one is fully redundant.

Example: `agent_build_prompt_first_attempt`, `agent_build_prompt_with_review_feedback`, and `agent_build_prompt_with_prior_failure` share a builder. Today `first_attempt` covers zero unique statements — the sibling-uniqueness rule catches this.

**Why:** Without it, one enriched fixture masks that its siblings exercise nothing the enriched one doesn't already cover.
