---
id: 0753
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T11:16:04.367426+00:00
status: active
corroborations: 1
supersedes: 0696
---

# wiki_rot_citations _STYLE_A_RE matches line refs as symbol cites

`_STYLE_A_RE` in `src/wiki_rot_citations.py` is `\b([\w./-]+\.py):(\w+)` — `\w+` also matches digits, so line refs (`base_background_loop.py:141`) get extracted as symbol cites. `verify_cite_ast` can never resolve a numeric symbol, so `WikiRotDetectorLoop` reports these broken forever.

Example: 12 distinct broken cites in `docs/wiki/` today, ≥5 are line refs/placeholders. Any new scan root must exclude numeric-symbol/placeholder candidates first.

**Why:** Without excluding numeric symbols, cite extraction triggers a permanent false-positive escalation storm after 3 attempts.
