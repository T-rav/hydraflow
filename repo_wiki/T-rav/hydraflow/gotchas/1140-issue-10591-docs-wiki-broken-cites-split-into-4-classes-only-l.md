---
id: 1140
topic: gotchas
source_issue: 10591
source_phase: plan
created_at: 2026-07-26T03:23:10.272140+00:00
status: superseded
corroborations: 1
superseded_by: 1144
---

# docs/wiki/ broken cites split into 4 classes; only line-ref FPs are #10591's scope

`WikiRotDetectorLoop`'s broken-cite count over `docs/wiki/` is not one bug — at #10591 plan time it was 13 total: 5 line-number refs (`orchestrator.py:948`, `phase_utils.py:392`, etc. — the regex FP), 2 doc placeholders (literal `path.py:symbol` examples in prose), 2 module-level constants, and 4 genuine rot needing real doc fixes. Fixing `_STYLE_A_RE` only zeroes the first class; the other three get separate `hydraflow-find` issues, not folded into this fix.

**Why:** don't expect `make quality` or the new audit script to report zero broken cites overall after this fix lands — only zero candidates in the line-reference class it targets.
