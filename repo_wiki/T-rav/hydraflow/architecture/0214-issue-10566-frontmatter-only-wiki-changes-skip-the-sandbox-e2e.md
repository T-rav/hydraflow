---
id: 0214
topic: architecture
source_issue: 10566
source_phase: plan
created_at: 2026-07-25T23:57:01.883165+00:00
status: active
corroborations: 1
---

# Frontmatter-only wiki changes skip the sandbox e2e tier — say so explicitly

For changes confined to `repo_wiki/**/*.md` frontmatter bookkeeping (supersession edges, no docker/UI surface touched), the three-layer pyramid from `docs/standards/testing/README.md` still applies for unit + `tests/scenarios/test_wiki_evolution_scenarios.py`, but sandbox e2e is legitimately N/A — state that explicitly in the PR rather than silently omitting it. Example: issue #10566's fix to `WikiCompiler.compile_topic_tracked` skips sandbox e2e with a stated reason.

**Why:** an unstated missing tier reads as an oversight to reviewers even when the layer genuinely doesn't apply.
