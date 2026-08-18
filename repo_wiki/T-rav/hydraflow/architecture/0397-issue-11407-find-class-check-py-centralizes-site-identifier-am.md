---
id: 0397
topic: architecture
source_issue: 11407
source_phase: plan
created_at: 2026-08-18T02:53:10.561508+00:00
status: active
corroborations: 1
---

# find_class_check.py centralizes site-identifier ambiguity by design

`scripts/find_class_check.py` deliberately uses site-identifier-only membership checks (`--check --site`) without distinguishing tagged vs untagged lines. Do not add tag-awareness here — the ambiguity is intentionally centralized so `src/find_class_key.py` is the single resolver.

After the #11407 bind fix, `find_class_check.py --check --site` against a legacy-line body reports `FOLD`, now consistent with what the fold actually does.

**Why:** Splitting ambiguity resolution across two modules creates silent divergence between the checker and the fold path.
