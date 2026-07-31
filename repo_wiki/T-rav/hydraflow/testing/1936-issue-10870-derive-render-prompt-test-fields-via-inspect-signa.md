---
id: 1936
topic: testing
source_issue: 10870
source_phase: plan
created_at: 2026-07-31T06:08:36.407893+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Derive render_prompt test fields via inspect.signature

When building the test render context for `preflight.runner.render_prompt`, derive the 12 keyword fields dynamically using `inspect.signature(render_prompt)` rather than a literal dictionary. Assert this signature equals the test's render fields minus `prompt_template`.

**Why:** Prevents silent drift between the runner's actual expected parameters and the test suite's hardcoded fields.
