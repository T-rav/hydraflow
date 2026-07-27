---
id: 1141
topic: gotchas
source_issue: 10590
source_phase: plan
created_at: 2026-07-26T04:12:39.569046+00:00
status: active
corroborations: 1
---

# Dedupe carried-forward claims by (pr_ref, code_refs), never strip model-echoed text

When `compile_topic_tracked` writes the deterministic claim union, dedupe against claims the LLM already echoed in its synthesis content by comparing `(pr_ref, code_refs)` tuples — don't strip or rewrite content that happens to quote the wiki schema. Also don't let an LLM-hallucinated `fixed_in_pr` mentioned in prose get promoted into the deterministic union; the union is sourced only from `_load_tracked_active_entries`, never from the model's freeform output.
**Why:** stripping legitimate schema-quoting content is a false positive, and trusting model prose for the union reintroduces the exact non-determinism issue #10590 exists to fix.
