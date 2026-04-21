<!-- docs/_prompt_audit_handoff.md — Section 6 of the generated report -->
## Handoff to sub-projects 2–4

- **Sub-project 2 (eval gate):** inherits `tests/fixtures/prompts/*.json` + `rendered/*.txt` as the gate's input corpus + baseline.
- **Sub-project 3 (shared template):** codifies the recurring tag vocabulary `<issue>`, `<plan>`, `<diff>`, `<history>`, `<constraints>`, `<manifest>`, `<prior_review>`, `<output_format>`, `<example>`, `<thinking>`.
- **Sub-project 4 (normalization PRs):** one PR per loop (Triage / Plan / Implement / Review / HITL) + one for Adjacent. Each PR must pass the sub-project 2 gate.
