---
id: 0431
topic: architecture
source_issue: 11868
source_phase: plan
created_at: 2026-09-01T03:50:35.471355+00:00
status: active
corroborations: 1
---

# Arch generators are deterministic: no gitignored reads, no check runs

Rule: Generators in `src/arch/generators/` must only consume repo-derived facts, never the gitignored ledger or live check output. See the `adr_conformance.py` docstring for the canonical pattern. `facts` is an injected parameter so a live caller can pass richer facts later; runtime-only standards (`adr_conformance`, `test_pyramid`) render as GAP rows naming that reason.

**Why:** Mixing live state into generators breaks byte-identical regeneration and makes `--check` non-deterministic.
