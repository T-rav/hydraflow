---
id: 0261
topic: architecture
source_issue: 10797
source_phase: plan
created_at: 2026-07-28T09:50:07.998833+00:00
status: active
corroborations: 1
---

# Evolve wiki_compiler helpers via delegate, keep old signature stable

When replacing a whole-topic check with a richer partition API, keep the old function as a thin delegate rather than rewriting call sites.

- `synthesis_matches_active_bodies` (`src/repo_wiki.py:421`) now delegates to `partition_noop_synthesis` with identical True/False semantics.
- All four existing #10573 regression cases return the same result unchanged.

**Why:** Inline replacement breaks untracked callers and guard-rail suites (#10573, #10590); delegation lets the partition land without a coordinated multi-module rewrite.
