---
id: 2741
topic: testing
source_issue: 11416
source_phase: plan
created_at: 2026-08-18T03:21:19.601687+00:00
status: active
corroborations: 1
---

# FakeWikiCompiler.compile_topic_tracked keyword-only vs positional call

Rule: `mockworld.fakes.FakeWikiCompiler.compile_topic_tracked` accepts `topic` as keyword-only, but `RepoWikiLoop` calls it positionally (#11409). When writing `repo_wiki` scenario tests, use a local duck-typed recording compiler with positional parameters.

**Why:** Using `FakeWikiCompiler` directly will raise `TypeError`; fixing the fake is tracked separately under #11409.
