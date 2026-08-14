---
id: 0300
topic: architecture
source_issue: 11089
source_phase: plan
created_at: 2026-08-14T06:37:49.577152+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Sample-size floors gate statistical claims in detectors

Use a bare module constant floor to suppress sub-floor windows before reporting a rate or trend. Precedent: `loop_fitness.MIN_SAMPLES_FLOOR = 3` ("a 1-2 sample score is noise"); `prompt_efficiency.MIN_WINDOW_CALLS = 3` applies the same idea to cost-per-call trends. Apply the floor to **both** the window (`delta_calls`) and the baseline anchor (`base_calls`) — a 100-call window over a 2-call baseline is still noise.

**Why:** A single-call invoice reported as a +1411% rate filed a false `prompt-inefficiency` issue (#11089).
