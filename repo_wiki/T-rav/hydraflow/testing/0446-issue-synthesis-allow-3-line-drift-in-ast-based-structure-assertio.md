---
id: 0446
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:46:15.867759+00:00
status: superseded
corroborations: 1
supersedes: 0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401,0402,0403,0404,0405,0406,0407,0408,0409,0410,0411
superseded_by: 0451
---

# Allow ±3 line drift in AST-based structure assertions

For tests that verify code structure by parsing source ASTs (e.g., checking function length), allow ±3 line tolerance.

Example: Assert `len(func.body) <= 53` rather than `<= 50` to account for blank lines and decorator variations. See also: testing — Enforce 50/30-line limits on handlers and wiring.

**Why:** Exact line-count assertions redden CI on whitespace-only diffs, creating maintenance noise without improving correctness.
