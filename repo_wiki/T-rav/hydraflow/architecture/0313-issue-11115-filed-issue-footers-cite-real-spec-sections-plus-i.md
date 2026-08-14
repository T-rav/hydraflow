---
id: 0313
topic: architecture
source_issue: 11115
source_phase: plan
created_at: 2026-08-14T10:03:17.496171+00:00
status: active
corroborations: 1
---

# Filed-issue footers cite real spec sections plus issue anchor

Filed-issue footers in `src/skill_prompt_eval_loop.py` follow the sibling pattern at L448/L467/L1092: cite the loop's own real spec section plus the originating issue anchor (e.g. `§4.6` + `#9724`). Never invent a heading like `§5c` that does not appear in the declared spec doc.

**Why:** Triagers who follow footer citations to non-existent sections hit dead ends and cannot trace design rationale.
