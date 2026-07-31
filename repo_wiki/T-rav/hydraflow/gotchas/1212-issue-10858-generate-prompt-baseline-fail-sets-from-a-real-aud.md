---
id: 1212
topic: gotchas
source_issue: 10858
source_phase: plan
created_at: 2026-07-31T01:20:45.119651+00:00
status: active
corroborations: 1
---

# Generate PROMPT_BASELINE fail sets from a real audit run, never hand-guess

`test_baseline_is_not_looser_than_reality` demands exact fail sets. Pinning `PROMPT_BASELINE` entries in `src/prompt_fitness.py` by hand-guessing produces false greens.

Run `make audit-prompts` against the real template render, capture the measured fail set, then pin it verbatim.

**Why:** A guessed baseline that omits a real failure makes the ratchet permanently blind to that defect; only a measured baseline keeps the floor honest.
