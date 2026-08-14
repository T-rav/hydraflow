---
id: 1718
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T11:12:31.740507+00:00
status: active
corroborations: 1
supersedes: 1624
---

# Prompt audit report must be byte-identical across machines (ADR-0116)

`make audit-prompts` must produce byte-identical output across machines. Verify by running twice — once ambient, once with `HYDRAFLOW_*` scrubbed — and diffing the report bytes.

Example: `PROMPT_BASELINE` drift is a contract violation under ADR-0116. If a score moves, re-pin with justification in the PR body; a silent `PROMPT_BASELINE` edit is indistinguishable from covering a regression.

**Why:** Without reproducibility, the audit corpus cannot serve as a measured contract for prompt fitness.
