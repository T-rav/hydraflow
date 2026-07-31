---
id: 1027
topic: patterns
source_issue: 10859
source_phase: plan
created_at: 2026-07-31T02:56:19.656601+00:00
status: superseded
corroborations: 1
superseded_by: 1094
---

# Prompt audit report must be byte-identical across machines (ADR-0116)

`make audit-prompts` must produce byte-identical output across machines. Verify by running twice — once ambient, once with `HYDRAFLOW_*` scrubbed — and diffing the report bytes.

- `PROMPT_BASELINE` drift is a contract violation under ADR-0116.
- If a score moves, re-pin with justification in the PR body; a silent `PROMPT_BASELINE` edit is indistinguishable from covering a regression.

**Why:** Without reproducibility, the audit corpus cannot serve as a measured contract for prompt fitness.
