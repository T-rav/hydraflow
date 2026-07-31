---
id: 1219
topic: gotchas
source_issue: 10865
source_phase: plan
created_at: 2026-07-31T02:25:44.330108+00:00
status: active
corroborations: 1
---

# Triple-quoted f-string pitfall in prompt scanning

When stripping f-string literals in `src/prompt_fitness.py`, explicitly pin and handle triple-quoted strings (`f"""..."""`).
A naive regex applied to `f"""x{y}"""` will match only `f""` and leak `{y}` into the scan.
**Why:** Mishandling triple quotes silently breaks the ADR-0116 §10 contract gate by generating false positives or missing leaks.
