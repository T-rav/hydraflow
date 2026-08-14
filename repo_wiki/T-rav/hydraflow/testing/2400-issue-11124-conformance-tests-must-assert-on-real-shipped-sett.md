---
id: 2400
topic: testing
source_issue: 11124
source_phase: plan
created_at: 2026-08-14T11:33:53.102499+00:00
status: active
corroborations: 1
---

# Conformance tests must assert on real shipped settings, not fixtures

Conformance tests in `tests/test_merge_assets.py` must parse the repo's actual shipped `.claude/settings.json`, not only synthetic fixtures. Existing coverage passed with zero tags because fixtures were pre-tagged.

Assert every hook object whose `command` references `.claude/hooks/hf.` carries `_hydraflow: true`, and every referenced script exists on disk under `.claude/hooks/`.

**Why:** Synthetic fixtures validate the merge algorithm but not that the real source data satisfies the algorithm's preconditions — the gap that let the bug ship.
