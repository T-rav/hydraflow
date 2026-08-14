---
id: 0302
topic: architecture
source_issue: 11093
source_phase: plan
created_at: 2026-08-14T06:48:30.313343+00:00
status: active
corroborations: 1
---

# Order prompt templates: invariant prefix, variable suffix last

Structure `_PROMPT_TEMPLATE` in `src/term_proposer_llm.py` as: invariant rubric (Step 1/Step 2/Output, ~3765 chars) → tick-stable ontology → per-candidate content last.

- Two prompts for different candidates against the same glossary must share a ≥3500-char prefix.
- Prompt semantics must not change — every inclusion rule, closed-set vocabulary, output shape, and anchor-subset constraint must survive the reorder.
- Candidate name, anchor, source, and caller snippets appear after the rubric.

**Why:** A cacheable invariant prefix only saves cost if the variable content sits at the tail; dropping a rule during reorder degrades draft quality invisibly for weeks.
