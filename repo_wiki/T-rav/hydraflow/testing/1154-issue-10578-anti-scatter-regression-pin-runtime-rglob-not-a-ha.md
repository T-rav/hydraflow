---
id: 1154
topic: testing
source_issue: 10578
source_phase: plan
created_at: 2026-07-26T01:20:17.466873+00:00
status: active
corroborations: 1
---

# Anti-scatter regression pin: runtime rglob, not a hardcoded module list

When writing a regression test to prove a literal (like `"escape_ledger.jsonl"`) resolves in exactly one file, scan `src/**/*.py` at runtime with `rglob` rather than asserting against a fixed list of module names. See `tests/regressions/test_issue_10578.py`'s intended guard: it must be red before the P2 migration and green after, and stays valid even if new modules are added later.
**Why:** a hardcoded module list silently stops catching new scatter sites as the codebase grows, defeating the pin's purpose.
