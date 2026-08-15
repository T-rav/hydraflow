---
id: 0323
topic: architecture
source_issue: 11135
source_phase: plan
created_at: 2026-08-14T13:08:51.035584+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Probe make target existence in shared pre-commit for managed repos

When adding `make <target>` calls to `.githooks/pre-commit` for HydraFlow-specific targets like `arch-validate`, guard with a target-existence probe so managed repos without the target skip cleanly instead of blocking the commit.

- Pattern: `make -q arch-validate 2>/dev/null && make arch-validate || true`
- Or: `grep -q '^arch-validate:' Makefile && make arch-validate`

**Why:** `.githooks/pre-commit` ships to onboarded repos whose Makefiles lack HydraFlow-specific targets; an unguarded call aborts every commit.
