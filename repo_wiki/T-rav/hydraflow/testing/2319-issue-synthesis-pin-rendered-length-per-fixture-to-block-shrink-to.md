---
id: 2319
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:37.018905+00:00
status: active
corroborations: 1
supersedes: 2174
---

# Pin rendered length per fixture to block shrink-to-N/A gaming

Pin rendered character length per fixture. Any edit that renders >5% shorter fails the build until the length pin is updated in the same commit.

Example: A prompt falling below 10,000 chars fails, naming criterion 6 turning N/A. ADR-0116 §7 names 'shrink-to-N/A' as an explicit gaming mode.

**Why:** Without length pins, shrinking a fixture to dodge `test_no_prompt_gains_a_failing_criterion` registers as a win instead of debt — the fixture got worse, not better.
