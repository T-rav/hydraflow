---
id: 0272
topic: architecture
source_issue: 10861
source_phase: plan
created_at: 2026-07-31T01:46:44.758688+00:00
status: active
corroborations: 1
---

# ADR citing src/ must be amended in the same PR as src/ changes

When modifying a module cited by an ADR — e.g. `docs/adr/0116-prompts-as-a-measured-contract.md` cites `src/prompt_fitness.py` — amend the ADR in the same PR.

- The drift auditor detects ADR↔src divergence and files a rollup issue if they land separately.
- Apply to any ADR with a `**Enforced by:**` or body reference to the changed module.

**Why:** Decoupling ADR amendments from their source changes triggers automated drift reports and pollutes the rollup queue.
