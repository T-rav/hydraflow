---
id: 0284
topic: architecture
source_issue: 10878
source_phase: plan
created_at: 2026-07-31T07:10:49.839641+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Generated gate artifacts (ruleset JSON, README table) — never hand-edit

`staging_ruleset.json`, `main_ruleset.json`, and the gates table in `docs/standards/branch_protection/README.md` are produced by `make gen-gates`. Edit `gates.toml` and regenerate; never hand-edit generated files.

Hand-edit surrounding prose (e.g. "2 required checks" → 3) only in non-generated README sections and `docs/wiki/patterns.md`.

**Why:** `python -m scripts.gen_gates --check` validates that generated artifacts match their `gates.toml` source. Hand-edited generated files fail `make gen-gates-check` and leave `Gates Drift` red.
