---
id: 4062
topic: patterns
source_issue: 11416
source_phase: plan
created_at: 2026-08-18T03:21:19.601636+00:00
status: stale
corroborations: 1
stale_reason: source issue #11416 closed
---

# Catalog builders must thread collaborator ports to loop constructors

Rule: In `tests/scenarios/catalog/loop_registrations.py`, every builder must pass optional collaborator ports from `ports` to the loop constructor, matching sibling builder conventions. Use `<loop>_<collab>` port keys (e.g., `repo_wiki_state`).

Example:
- `_build_repo_wiki` must pass `wiki_compiler=ports.get("wiki_compiler")`, plus `state` and `tribal_store` (gated at `src/repo_wiki_loop.py:652`).
- Each touched builder's docstring names its new port key.

**Why:** When a port is omitted, the loop's `is None`-guard silently builds a real collaborator — `_CLIRefineLLM` spawns a `claude` subprocess, `EscapeAutoDiagnoser` does live git reads — instead of using the scenario's fake.
