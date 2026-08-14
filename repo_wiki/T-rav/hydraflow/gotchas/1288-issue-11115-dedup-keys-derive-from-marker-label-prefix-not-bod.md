---
id: 1288
topic: gotchas
source_issue: 11115
source_phase: plan
created_at: 2026-08-14T10:03:17.496144+00:00
status: active
corroborations: 1
---

# Dedup keys derive from marker-label prefix, not body text

Changing body text in filed issues is safe — dedup keys in hydraflow derive from the marker-label prefix, not body content. Repointing `§5c` to `§4.6` in `src/skill_prompt_eval_loop.py`'s filed `prompt-inefficiency` footer does not re-file open issues.

**Why:** If dedup keys hashed body text, any footer or citation fix would create duplicate issues, blocking safe corrections.
