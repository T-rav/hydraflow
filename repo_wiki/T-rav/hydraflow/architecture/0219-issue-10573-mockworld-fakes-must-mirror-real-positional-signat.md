---
id: 0219
topic: architecture
source_issue: 10573
source_phase: plan
created_at: 2026-07-26T00:55:00.255834+00:00
status: active
corroborations: 1
---

# MockWorld fakes must mirror real positional signatures, not just arg names

`src/mockworld/fakes/fake_wiki_compiler.py`'s `compile_topic_tracked` accepted args keyword-only, but the real compiler signature is `(tracked_root, repo, topic, *, other_topics=None)` — positional for the first three. A MockWorld scenario (`tests/scenarios/test_wiki_evolution_scenarios.py`) calling it the real way hits `TypeError` until the fake matches.

**Why:** a fake that diverges from the real callable's positional/keyword signature passes in isolation but breaks the first time a scenario exercises the actual production call pattern — check fake signatures against the real module whenever a scenario fails with an unexpected-keyword-argument `TypeError`.
