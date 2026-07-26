---
id: 0234
topic: architecture
source_issue: 10613
source_phase: plan
created_at: 2026-07-26T10:32:19.699634+00:00
status: active
corroborations: 1
---

# Avoid `src/secrets/` directory to prevent stdlib shadowing

Use `src/secrets_provider/` instead of `src/secrets/` for new secrets modules. The `src/` directory is flat on `sys.path`, so `src/secrets/` shadows the Python stdlib `secrets` module.
- Breaks imports in `term_proposer_loop`, `entry_evidence_loop`, `term_pruner_loop`, and `edge_proposer_loop`.
**Why:** Shadowing stdlib causes silent, system-wide import failures for existing background loops.
