---
id: 1720
topic: testing
source_issue: 10860
source_phase: plan
created_at: 2026-07-31T01:48:16.698188+00:00
status: superseded
corroborations: 1
superseded_by: 1813
---

# Pin rendered length per fixture to block shrink-to-N/A gaming

Pin rendered character length per fixture. Any edit that renders >5% shorter fails the build until the length pin is updated in the same commit.

Example: A prompt falling below 10,000 chars fails, naming criterion 6 turning N/A. ADR-0116 §7 names "shrink-to-N/A" as an explicit gaming mode.

**Why:** Without length pins, shrinking a fixture to dodge `test_no_prompt_gains_a_failing_criterion` registers as a win instead of debt — the fixture got worse, not better.
