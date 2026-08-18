---
id: 2742
topic: testing
source_issue: 11415
source_phase: plan
created_at: 2026-08-18T03:26:10.006489+00:00
status: active
corroborations: 1
---

# Directional kind comparison in _signatures_compatible

In `tests/test_mockworld_fakes_conformance.py`, `_signatures_compatible` must compare `inspect.Parameter.kind` directionally — reject only where the fake is stricter than the reference, never where it's more permissive.

- Reference calls positionally, fake declares `KEYWORD_ONLY` → fail.
- Fake widens keyword-only to positional-or-keyword → pass.
- Params both sides take positionally must share the same index.

**Why:** A fake that narrows a param breaks real callers like `repo_wiki_loop.py:441` passing `tracked_root, repo, topic` positionally to `compile_topic_tracked`.
